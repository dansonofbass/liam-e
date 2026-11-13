"""Parse Gmail API full-format messages."""

import base64
import json
from datetime import UTC, datetime
from typing import Any

import httpx
from db.models.mail_account import MailAccount

from api.mail import providers, service
from api.mail.sync_types import SyncChanges, addresses, common


async def fetch_changes(account: MailAccount, *, cursor: str, folders: list[str], limit: int, max_body_chars: int) -> SyncChanges:
    credentials = await service.load_credentials(account)
    token = await service.valid_access_token(account, credentials)
    headers = {"Authorization": f"Bearer {token}"}
    changes = SyncChanges(cursor=cursor)
    async with httpx.AsyncClient(timeout=30, base_url=providers.GMAIL_API) as client:
        ids: set[str] = set()
        rebuild = not cursor
        if cursor:
            page_token = ""
            while True:
                params: dict[str, Any] = {"startHistoryId": cursor, "maxResults": max(1, min(limit, 500)), "historyTypes": ["messageAdded", "labelAdded", "labelRemoved", "messageDeleted"]}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get("/history", params=params, headers=headers)
                if response.status_code == 404:
                    rebuild = True
                    break
                response.raise_for_status()
                page = response.json()
                changes.cursor = page.get("historyId", changes.cursor)
                for event in page.get("history", []):
                    for kind in ("messagesAdded", "labelsAdded", "labelsRemoved", "messagesDeleted"):
                        for entry in event.get(kind, []):
                            if entry.get("message", {}).get("id"):
                                ids.add(entry["message"]["id"])
                page_token = page.get("nextPageToken", "")
                if not page_token:
                    break
                history = page.get("history", [])
                if len(ids) >= limit and history and history[-1].get("id"):
                    changes.cursor = str(history[-1]["id"])
                    break
        if rebuild:
            ids.clear()
            changes = SyncChanges(full_rebuild=True)
            profile = await client.get("/profile", headers=headers)
            profile.raise_for_status()
            changes.cursor = profile.json().get("historyId", "")
            page_token = ""
            while len(ids) < limit:
                params = {"q": "in:inbox", "maxResults": min(500, limit - len(ids))}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get("/messages", params=params, headers=headers)
                response.raise_for_status()
                page = response.json()
                ids.update(ref["id"] for ref in page.get("messages", []))
                page_token = page.get("nextPageToken", "")
                if not page_token:
                    break
        for uid in ids:
            response = await client.get(f"/messages/{uid}", params={"format": "full"}, headers=headers)
            if response.status_code == 404:
                changes.moved_out.append(uid)
                continue
            response.raise_for_status()
            message = response.json()
            if "INBOX" not in message.get("labelIds", []):
                changes.moved_out.append(uid)
                continue
            changes.upserts.append(parse_message(message, max_body_chars=max_body_chars))
    return changes


def parse_message(message: dict[str, Any], *, max_body_chars: int) -> dict[str, Any]:
    payload = message.get('payload') or {}
    headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}
    files: list[dict[str, Any]] = []
    texts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        filename = part.get('filename')
        body = part.get('body') or {}
        if filename:
            files.append({'name': filename, 'size': body.get('size', 0), 'content_type': part.get('mimeType', '')})
        elif part.get('mimeType') == 'text/plain' and body.get('data'):
            data = body['data']
            texts.append(base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode(errors='replace'))
        for child in part.get('parts') or []:
            walk(child)

    walk(payload)
    body = '\n'.join(texts)[:max_body_chars]
    labels = message.get('labelIds') or []
    sender = headers.get('from', '')
    return {**common(sender, headers), 'folder': 'INBOX', 'provider_uid': message['id'],
            'thread_id': message.get('threadId', ''), 'subject': headers.get('subject', ''),
            'sender': sender, 'recipients_json': addresses(headers.get('to', '')),
            'cc_json': addresses(headers.get('cc', '')), 'snippet': ' '.join((message.get('snippet') or body).split())[:500],
            'body_text': body, 'internal_date': datetime.fromtimestamp(int(message['internalDate']) / 1000, tz=UTC) if message.get('internalDate') else None,
            'has_attachments': bool(files), 'attachments_json': json.dumps(files),
            'is_read': 'UNREAD' not in labels, 'is_flagged': 'STARRED' in labels, 'labels_json': json.dumps(labels)}
