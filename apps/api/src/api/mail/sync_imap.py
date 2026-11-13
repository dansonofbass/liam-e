"""Parse RFC 822 messages fetched over IMAP."""

import email
import json
from datetime import UTC
from email import policy
from email.utils import parsedate_to_datetime
from typing import Any

from api.mail.headers import sender_address
from api.mail.sync_types import addresses, common


def parse_rfc822(raw: bytes, *, max_body_chars: int) -> dict[str, Any]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    parts, files = [], []
    for part in msg.walk():
        try:
            filename = part.get_filename()
            if filename or part.get_content_disposition() == "attachment":
                payload = part.get_payload(decode=True) or b""
                files.append({"name": filename or "", "size": len(payload), "content_type": part.get_content_type()})
            elif part.get_content_type() == "text/plain":
                content = part.get_content()
                if isinstance(content, str):
                    parts.append(content)
        except Exception:
            pass
    body = '\n'.join(parts)[:max_body_chars]
    def header(key: str) -> str:
        try:
            return str(msg.get(key, ""))
        except Exception:
            return ""

    def mailbox_addresses(key: str) -> list[str] | None:
        try:
            values = msg.get_all(key, [])
            if not all(hasattr(value, "addresses") for value in values):
                return None
            return [address.addr_spec for value in values for address in value.addresses if address.username and address.domain]
        except Exception:
            return None

    try:
        date = parsedate_to_datetime(header("date"))
        if date and date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        date = None
    hdr = {key.lower(): header(key) for key, _ in msg.raw_items()}
    raw_from = next((value for key, value in msg.raw_items() if key.lower() == "from"), "")
    sender = header("from")
    sender_fields = common(raw_from, hdr)
    sender_fields["sender_address"] = sender_address(raw_from)
    to_addresses = mailbox_addresses("to")
    cc_addresses = mailbox_addresses("cc")
    return {**sender_fields, "thread_id": hdr.get("message-id", ""),
            "subject": header("subject"), "sender": sender,
            "recipients_json": json.dumps(to_addresses) if to_addresses is not None else addresses(header("to")),
            "cc_json": json.dumps(cc_addresses) if cc_addresses is not None else addresses(header("cc")),
            'snippet': ' '.join(body.split())[:500], 'body_text': body,
            'internal_date': date, 'has_attachments': bool(files),
            'attachments_json': json.dumps(files), 'is_read': False,
            'is_flagged': False, 'labels_json': '[]'}
