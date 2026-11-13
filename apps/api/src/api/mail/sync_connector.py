"""Parse Studio connector messages; full-content responses do not expose headers."""

import json
from datetime import datetime
from typing import Any

from api.mail.sync_types import attachments, common, strip_html


def parse_message(message: dict[str, Any], *, thread_id: str, folder: str, max_body_chars: int) -> dict[str, Any]:
    body = (message.get('plaintextBody') or strip_html(message.get('htmlBody') or ''))[:max_body_chars]
    labels = message.get('labelIds') or []
    sender = message.get('sender') or ''
    try:
        date = datetime.fromisoformat(message['date']) if message.get('date') else None
    except ValueError:
        date = None
    files = attachments(message.get('attachments') or [])
    return {**common(sender, {}), 'folder': folder, 'provider_uid': message['id'],
            'thread_id': thread_id, 'subject': message.get('subject') or '', 'sender': sender,
            'recipients_json': json.dumps(message.get('toRecipients') or []), 'cc_json': json.dumps(message.get('ccRecipients') or []),
            'snippet': ' '.join((message.get('snippet') or body).split())[:500], 'body_text': body,
            'internal_date': date, 'has_attachments': bool(message.get('attachmentIds') or files),
            'attachments_json': json.dumps(files), 'is_read': 'UNREAD' not in labels,
            'is_flagged': 'STARRED' in labels, 'labels_json': json.dumps(labels)}
