"""Parse Microsoft Graph messages."""

import json
from datetime import datetime
from typing import Any

from api.mail.sync_types import attachments, common, strip_html


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
