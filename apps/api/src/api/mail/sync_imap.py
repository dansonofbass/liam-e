"""Parse RFC 822 messages fetched over IMAP."""

import email
import json
from datetime import UTC
from email import policy
from email.utils import parsedate_to_datetime
from typing import Any

from api.mail.sync_types import addresses, common


def parse_rfc822(raw: bytes, *, max_body_chars: int) -> dict[str, Any]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    parts, files = [], []
    for part in msg.walk():
        filename = part.get_filename()
        if filename or part.get_content_disposition() == 'attachment':
            payload = part.get_payload(decode=True) or b''
            files.append({'name': filename or '', 'size': len(payload), 'content_type': part.get_content_type()})
        elif part.get_content_type() == 'text/plain':
            try:
                content = part.get_content()
                if isinstance(content, str):
                    parts.append(content)
            except (LookupError, UnicodeError, ValueError):
                pass
    body = '\n'.join(parts)[:max_body_chars]
    try:
        date = parsedate_to_datetime(str(msg.get('date', '')))
        if date and date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        date = None
    hdr = {key.lower(): str(value) for key, value in msg.items()}
    sender = str(msg.get('from', ''))
    return {**common(sender, hdr), 'thread_id': hdr.get('message-id', ''),
            'subject': str(msg.get('subject', '')), 'sender': sender,
            'recipients_json': addresses(', '.join(msg.get_all('to', []))),
            'cc_json': addresses(', '.join(msg.get_all('cc', []))),
            'snippet': ' '.join(body.split())[:500], 'body_text': body,
            'internal_date': date, 'has_attachments': bool(files),
            'attachments_json': json.dumps(files), 'is_read': False,
            'is_flagged': False, 'labels_json': '[]'}
