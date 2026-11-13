"""Parse Gmail API full-format messages."""

import base64
import json
from datetime import UTC, datetime
from typing import Any

from api.mail.sync_types import addresses, common


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
