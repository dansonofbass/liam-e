"""Parse Microsoft Graph messages."""

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from api.mail.providers import GRAPH_API
from api.mail.sync_types import attachments, common, strip_html


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
            if next_url.scheme != "https" or next_url.host != httpx.URL(GRAPH_API).host or "@" in urlsplit(url).netloc:
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
