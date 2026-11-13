"""Sync connected mail accounts into the local ``mail_message`` index.

Three provider paths: IMAP (imaplib, blocking calls in a worker thread), the Gmail REST API, and
Microsoft Graph (both via httpx). Bodies are capped at ``MAIL_SYNC_MAX_BODY_CHARS``. Progress lands
in ``mail_sync_state`` so a later run can continue from the provider cursor.
"""

from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import json
import logging
import re
from datetime import UTC, datetime
from email import policy
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

import httpx
from db.accessors import mail_account as account_access
from db.accessors import mail_message as message_access
from db.accessors import mail_sync_state as sync_state_access
from db.models.mail_account import MailAccount
from env.mail import env as mail_env

from api.mail import connectors, providers, service, transport

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _part_text(part: Message) -> str:
    """The decoded text of one part, or "" when its charset or payload cannot be decoded."""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, ValueError):
        return ""
    return content if isinstance(content, str) else ""


def _text_parts(msg: Message) -> tuple[str, bool]:
    """Concatenated text/plain parts and whether any attachment part exists."""
    parts: list[str] = []
    has_attachments = False
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            has_attachments = True
            continue
        if part.get_content_type() != "text/plain":
            continue
        content = _part_text(part)
        if content:
            parts.append(content)
    return "\n".join(parts), has_attachments


def _parse_rfc822(raw: bytes, *, max_body_chars: int) -> dict[str, Any]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    body, has_attachments = _text_parts(msg)
    body = body[:max_body_chars]
    recipients = [
        addr
        for _, addr in getaddresses(msg.get_all("to", []) + msg.get_all("cc", []))
        if addr
    ]
    return {
        "thread_id": str(msg.get("message-id", "")),
        "subject": str(msg.get("subject", "")),
        "sender": str(msg.get("from", "")),
        "recipients_json": json.dumps(recipients),
        "snippet": " ".join(body.split())[:500],
        "body_text": body,
        "internal_date": _parse_date(str(msg.get("date", ""))),
        "has_attachments": has_attachments,
    }


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


def _gmail_body(payload: dict[str, Any]) -> str:
    """The text/plain body of a Gmail payload, decoded from base64url, walking nested parts."""
    if payload.get("mimeType", "").startswith("text/") and payload.get("body", {}).get(
        "data"
    ):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            errors="replace"
        )
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                errors="replace"
            )
        nested = _gmail_body(part)
        if nested:
            return nested
    return ""


def _parse_gmail(message: dict[str, Any], *, max_body_chars: int) -> dict[str, Any]:

    headers = {
        h["name"].lower(): h["value"]
        for h in message.get("payload", {}).get("headers", [])
    }
    body = _gmail_body(message.get("payload", {}))[:max_body_chars]
    internal_date = None
    if message.get("internalDate"):
        internal_date = datetime.fromtimestamp(
            int(message["internalDate"]) / 1000, tz=UTC
        )
    return {
        "folder": "INBOX",
        "provider_uid": message["id"],
        "thread_id": message.get("threadId", ""),
        "subject": headers.get("subject", ""),
        "sender": headers.get("from", ""),
        "recipients_json": json.dumps([headers.get("to", "")]),
        "snippet": " ".join((message.get("snippet") or body).split())[:500],
        "body_text": body,
        "internal_date": internal_date,
        "has_attachments": any(
            p.get("filename") for p in message.get("payload", {}).get("parts", [])
        ),
        "labels_json": json.dumps(message.get("labelIds", [])),
    }


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


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _parse_graph(
    message: dict[str, Any], *, folder: str, max_body_chars: int
) -> dict[str, Any]:

    body = message.get("body", {})
    content = body.get("content", "")
    text = (
        _strip_html(content)
        if body.get("contentType", "").lower() == "html"
        else content
    )
    text = text[:max_body_chars]
    recipients = [
        r["emailAddress"]["address"]
        for r in message.get("toRecipients", []) + message.get("ccRecipients", [])
    ]
    received = message.get("receivedDateTime", "")
    # Python >= 3.11 fromisoformat parses a trailing "Z" itself.
    internal_date = datetime.fromisoformat(received) if received else None
    return {
        "folder": folder,
        "provider_uid": message["id"],
        "thread_id": message.get("conversationId", ""),
        "subject": message.get("subject", ""),
        "sender": message.get("from", {}).get("emailAddress", {}).get("address", ""),
        "recipients_json": json.dumps(recipients),
        "snippet": " ".join(text.split())[:500],
        "body_text": text,
        "internal_date": internal_date,
        "has_attachments": bool(message.get("hasAttachments")),
        "is_read": bool(message.get("isRead")),
    }


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
                    "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,isRead",
                },
                headers=headers,
            )
            response.raise_for_status()
            page = response.json()
            cursor = page.get("@odata.deltaLink", page.get("@odata.nextLink", cursor))
            for item in page.get("value", []):
                messages.append(
                    _parse_graph(item, folder=folder, max_body_chars=max_body_chars)
                )
    return messages, cursor


def _parse_connector_message(
    message: dict[str, Any], *, thread_id: str, folder: str, max_body_chars: int
) -> dict[str, Any]:
    """Map one message of a connector ``get_thread`` result onto a ``mail_message`` upsert."""
    body = message.get("plaintextBody") or _strip_html(message.get("htmlBody") or "")
    body = body[:max_body_chars]
    labels = message.get("labelIds") or []
    recipients = list(message.get("toRecipients") or []) + list(
        message.get("ccRecipients") or []
    )
    internal_date = None
    if message.get("date"):
        try:
            internal_date = datetime.fromisoformat(message["date"])
        except ValueError:
            internal_date = None
    return {
        "folder": folder,
        "provider_uid": message["id"],
        "thread_id": thread_id,
        "subject": message.get("subject", ""),
        "sender": message.get("sender", ""),
        "recipients_json": json.dumps(recipients),
        "snippet": " ".join((message.get("snippet") or body).split())[:500],
        "body_text": body,
        "internal_date": internal_date,
        "has_attachments": bool(message.get("attachmentIds")),
        "is_read": "UNREAD" not in labels,
        "labels_json": json.dumps(labels),
    }


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
            data = await connectors.call_tool_json(
                account.provider, "search_threads", args
            )
            for thread in data.get("threads", []):
                full = await connectors.call_tool_json(
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
