"""Sync connected mail accounts into the local ``mail_message`` index.

Three provider paths: IMAP (imaplib, blocking calls in a worker thread), the Gmail REST API, and
Microsoft Graph (both via httpx). Bodies are capped at ``MAIL_SYNC_MAX_BODY_CHARS``. Progress lands
in ``mail_sync_state`` so a later run can continue from the provider cursor.
"""

from __future__ import annotations

import asyncio
import imaplib
import logging
from typing import Any

import httpx
from db.accessors import mail_account as account_access
from db.accessors import mail_message as message_access
from db.accessors import mail_sync_state as sync_state_access
from db.models.mail_account import MailAccount
from env.mail import env as mail_env

from api.mail import connectors, providers, service, transport
from api.mail.sync_imap import parse_rfc822 as _parse_rfc822
from api.mail.sync_gmail import parse_message as _parse_gmail
from api.mail.sync_graph import parse_message as _parse_graph
from api.mail.sync_connector import parse_message as _parse_connector_message

logger = logging.getLogger(__name__)


def _fetch_imap(
    *,
    email_address: str,
    password: str,
    host: str,
    port: int,
    folders: list[str],
    limit: int,
    max_body_chars: int,
) -> tuple[list[dict[str, Any]], str]:
    """Blocking IMAP fetch of the newest ``limit`` messages per folder; runs in a worker thread."""
    connection = transport.open_imap(host, port)
    messages: list[dict[str, Any]] = []
    cursor = ""
    try:
        connection.login(email_address, password)
        for folder in folders:
            status, _ = connection.select(f'"{folder}"', readonly=True)
            if status != "OK":
                continue
            uidvalidity = (
                connection.response("UIDVALIDITY")[1][0].decode()
                if connection.response("UIDVALIDITY")[1]
                else ""
            )
            status, data = connection.uid("search", None, "ALL")
            uids = data[0].split() if data and data[0] else []
            last_uid = uids[-1].decode() if uids else ""
            cursor = f"{uidvalidity}:{last_uid}"
            for uid in uids[-limit:]:
                status, fetched = connection.uid("fetch", uid, "(RFC822)")
                raw = next(
                    (
                        part[1]
                        for part in fetched
                        if isinstance(part, tuple) and part[1]
                    ),
                    None,
                )
                if raw is None:
                    continue
                parsed = _parse_rfc822(raw, max_body_chars=max_body_chars)
                parsed["folder"] = folder
                parsed["provider_uid"] = uid.decode()
                messages.append(parsed)
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            logger.debug("IMAP logout after sync failed")
    return messages, cursor


async def _sync_gmail(
    token: str, *, folders: list[str], limit: int, max_body_chars: int
) -> tuple[list[dict[str, Any]], str]:
    headers = {"Authorization": f"Bearer {token}"}
    messages: list[dict[str, Any]] = []
    cursor = ""
    async with httpx.AsyncClient(timeout=30, base_url=providers.GMAIL_API) as client:
        for folder in folders:
            response = await client.get(
                "/messages",
                params={"maxResults": limit, "q": f"in:{folder.lower()}"},
                headers=headers,
            )
            response.raise_for_status()
            listing = response.json()
            cursor = listing.get("historyId", cursor)
            for ref in listing.get("messages", []):
                detail = await client.get(
                    f"/messages/{ref['id']}", params={"format": "full"}, headers=headers
                )
                detail.raise_for_status()
                messages.append(
                    _parse_gmail(detail.json(), max_body_chars=max_body_chars)
                )
    return messages, cursor


async def _sync_graph(
    token: str, *, folders: list[str], limit: int, max_body_chars: int
) -> tuple[list[dict[str, Any]], str]:
    headers = {"Authorization": f"Bearer {token}"}
    messages: list[dict[str, Any]] = []
    cursor = ""
    async with httpx.AsyncClient(timeout=30, base_url=providers.GRAPH_API) as client:
        for folder in folders:
            response = await client.get(
                f"/me/mailFolders/{folder}/messages",
                params={
                    "$top": limit,
                    "$orderby": "receivedDateTime desc",
                    "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,isRead,internetMessageId,internetMessageHeaders,flag",
                },
                headers=headers,
            )
            response.raise_for_status()
            page = response.json()
            cursor = page.get("@odata.deltaLink", page.get("@odata.nextLink", cursor))
            for item in page.get("value", []):
                if item.get("hasAttachments"):
                    attachment_response = await client.get(
                        f"/me/messages/{item['id']}/attachments",
                        params={"$select": "name,size,contentType"}, headers=headers,
                    )
                    attachment_response.raise_for_status()
                    item["attachments"] = attachment_response.json().get("value", [])
                messages.append(
                    _parse_graph(item, folder=folder, max_body_chars=max_body_chars)
                )
    return messages, cursor


async def _sync_connector(
    account: MailAccount, *, folders: list[str], limit: int, max_body_chars: int
) -> tuple[list[dict[str, Any]], str]:
    """Sync a Mistral Studio connector (gmail & co.) via its search_threads/get_thread tools."""
    messages: list[dict[str, Any]] = []
    cursor = ""
    for folder in folders:
        page_token = ""
        while len(messages) < limit:
            args: dict[str, Any] = {
                "query": f"in:{folder.lower()}",
                "pageSize": min(50, limit - len(messages)),
            }
            if page_token:
                args["pageToken"] = page_token
            data = await connectors.call_read_tool_json(
                account.provider, "search_threads", args
            )
            for thread in data.get("threads", []):
                full = await connectors.call_read_tool_json(
                    account.provider,
                    "get_thread",
                    {"threadId": thread.get("id", ""), "messageFormat": "FULL_CONTENT"},
                )
                thread_id = full.get("id") or thread.get("id", "")
                for message in full.get("messages", []):
                    messages.append(
                        _parse_connector_message(
                            message,
                            thread_id=thread_id,
                            folder=folder,
                            max_body_chars=max_body_chars,
                        )
                    )
                    if len(messages) >= limit:
                        break
            page_token = data.get("nextPageToken") or ""
            cursor = page_token
            if not page_token or len(messages) >= limit:
                break
    return messages, cursor


async def sync_account(account_id: str) -> dict[str, Any]:
    """Sync one account into ``mail_message``; always returns a status dict, never raises for provider errors."""
    account = await account_access.get_account(account_id)
    if account is None:
        raise LookupError(f"no mail account with id {account_id}")
    previous = await sync_state_access.get_state(account_id)
    cursor = previous.cursor if previous is not None else ""
    await sync_state_access.save_state(
        account_id=account_id, cursor=cursor, status="syncing"
    )
    try:
        folders = [
            f.strip().upper()
            for f in mail_env.mail_sync_folders.split(",")
            if f.strip()
        ]
        limit = mail_env.mail_sync_page_size
        max_body_chars = mail_env.mail_sync_max_body_chars
        if account.auth_type == connectors.CONNECTOR:
            messages, cursor = await _sync_connector(
                account, folders=folders, limit=limit, max_body_chars=max_body_chars
            )
        elif account.provider == providers.IMAP:
            credentials = await service.load_credentials(account)
            await transport.check_mail_host(credentials["imap_host"])
            password = await service.imap_password(credentials)
            messages, cursor = await asyncio.to_thread(
                _fetch_imap,
                email_address=account.email_address,
                password=password,
                host=credentials["imap_host"],
                port=int(credentials.get("imap_port", 993)),
                folders=folders,
                limit=limit,
                max_body_chars=max_body_chars,
            )
        elif account.provider == providers.GOOGLE:
            credentials = await service.load_credentials(account)
            token = await service.valid_access_token(account, credentials)
            messages, cursor = await _sync_gmail(
                token, folders=folders, limit=limit, max_body_chars=max_body_chars
            )
        elif account.provider == providers.MICROSOFT:
            credentials = await service.load_credentials(account)
            token = await service.valid_access_token(account, credentials)
            messages, cursor = await _sync_graph(
                token, folders=folders, limit=limit, max_body_chars=max_body_chars
            )
        else:
            raise ValueError(f"unknown provider {account.provider!r}")
        for parsed in messages:
            await message_access.upsert_message(account_id=account.id, **parsed)
        state = await sync_state_access.save_state(
            account_id=account_id, cursor=cursor, status="ok"
        )
        return {
            "status": "ok",
            "synced": len(messages),
            "cursor": state.cursor,
            "last_error": "",
        }
    except Exception:  # noqa: BLE001 — never expose provider errors or credentials
        message = "Die Mails konnten nicht abgerufen werden. Prüfe die Kontoeinstellungen und versuch es noch einmal."
        state = await sync_state_access.save_state(
            account_id=account_id, cursor=cursor, status="error", last_error=message
        )
        return {
            "status": "error",
            "synced": 0,
            "cursor": state.cursor,
            "last_error": message,
        }
