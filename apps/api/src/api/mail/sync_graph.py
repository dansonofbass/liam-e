"""Parse Microsoft Graph messages."""

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from db.models.mail_account import MailAccount

from api.mail import service
from api.mail.providers import GRAPH_API
from api.mail.sync_types import SyncChanges, attachments, common, strip_html


def _safe_delta_url(url: str) -> bool:
    parsed = httpx.URL(url)
    base = httpx.URL(GRAPH_API)
    return (parsed.scheme == "https" and parsed.host == base.host
            and (parsed.port or 443) == (base.port or 443)
            and "@" not in urlsplit(url).netloc)


async def fetch_changes(account: MailAccount, *, cursor: str, folders: list[str], limit: int, max_body_chars: int) -> SyncChanges:
    credentials = await service.load_credentials(account)
    token = await service.valid_access_token(account, credentials)
    headers = {"Authorization": f"Bearer {token}", "Prefer": f"odata.maxpagesize={max(1, limit)}"}
    changes = SyncChanges(cursor=cursor, full_rebuild=not cursor)
    url = cursor or "/me/mailFolders/inbox/messages/delta"
    params = None if cursor else {"$top": str(limit), "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,isRead,internetMessageId,internetMessageHeaders,flag"}
    latest: dict[str, dict[str, Any] | None] = {}
    async with httpx.AsyncClient(timeout=30, base_url=GRAPH_API) as client:
        while url:
            if url != "/me/mailFolders/inbox/messages/delta" and not _safe_delta_url(url):
                raise ValueError("Invalid Graph delta URL")
            response = await client.get(url, params=params, headers=headers, follow_redirects=False)
            response.raise_for_status()
            page = response.json()
            for item in page.get("value", []):
                if "@removed" in item:
                    latest[item["id"]] = None
                else:
                    if item.get("hasAttachments"):
                        item["attachments"] = await fetch_attachments(client, item["id"], headers)
                    latest[item["id"]] = parse_message(item, folder="INBOX", max_body_chars=max_body_chars)
            url = page.get("@odata.nextLink", "")
            params = None
            if url and len(latest) >= limit:
                if not _safe_delta_url(url):
                    raise ValueError("Invalid Graph next link")
                changes.cursor = url
                break
            if not url:
                changes.cursor = page.get("@odata.deltaLink", "")
                if not changes.cursor or not _safe_delta_url(changes.cursor):
                    raise ValueError("Missing or invalid Graph delta link")
    changes.upserts = [item for item in latest.values() if item is not None]
    changes.moved_out = [uid for uid, item in latest.items() if item is None]
    return changes


async def fetch_attachments(
    client: httpx.AsyncClient, message_id: str, headers: dict[str, str]
) -> list[dict[str, Any]] | None:
    url = f"/me/messages/{message_id}/attachments"
    params: dict[str, str] | None = {"$select": "name,size,contentType"}
    items: list[dict[str, Any]] = []
    try:
        for _ in range(5):
            response = await client.get(url, params=params, headers=headers, follow_redirects=False)
            response.raise_for_status()
            page = response.json()
            items.extend(page.get("value", []))
            url = page.get("@odata.nextLink")
            if not url:
                break
            next_url = httpx.URL(url)
            base_url = httpx.URL(GRAPH_API)
            next_port = next_url.port if next_url.port is not None else 443
            base_port = base_url.port if base_url.port is not None else 443
            if (next_url.scheme != "https" or next_url.host != base_url.host
                    or next_port != base_port or "@" in urlsplit(url).netloc):
                return None
            params = None
    except Exception:
        return None
    return items


def parse_message(message: dict[str, Any], *, folder: str, max_body_chars: int) -> dict[str, Any]:
    body = message.get('body') or {}
    text = body.get('content') or ''
    if body.get('contentType', '').lower() == 'html':
        text = strip_html(text)
    text = text[:max_body_chars]
    sender = (message.get('from') or {}).get('emailAddress', {}).get('address', '')
    headers = {h['name'].lower(): h['value'] for h in message.get('internetMessageHeaders') or []}
    headers['message-id'] = message.get('internetMessageId') or headers.get('message-id', '')
    def recipients(key: str) -> str:
        return json.dumps([r.get('emailAddress', {}).get('address', '') for r in message.get(key) or [] if r.get('emailAddress', {}).get('address')])
    received = message.get('receivedDateTime')
    return {**common(sender, headers), 'folder': folder, 'provider_uid': message['id'],
            'thread_id': message.get('conversationId', ''), 'subject': message.get('subject') or '',
            'sender': sender, 'recipients_json': recipients('toRecipients'), 'cc_json': recipients('ccRecipients'),
            'snippet': ' '.join(text.split())[:500], 'body_text': text,
            'internal_date': datetime.fromisoformat(received) if received else None,
            'has_attachments': bool(message.get('hasAttachments')), 'attachments_json': json.dumps(attachments(message.get('attachments') or [])),
            'is_read': bool(message.get('isRead')), 'is_flagged': (message.get('flag') or {}).get('flagStatus', '').lower() == 'flagged', 'labels_json': '[]'}
