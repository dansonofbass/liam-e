"""Shared helpers for provider message parsers."""

import json
import re
from email.utils import getaddresses
from typing import Any

from api.mail.headers import sender_address


def addresses(value: str) -> str:
    return json.dumps([address for _, address in getaddresses([value]) if address])


def common(sender: str, headers: dict[str, str]) -> dict[str, Any]:
    return {
        'sender_address': sender_address(sender),
        'rfc_message_id': headers.get('message-id', ''),
        'references': headers.get('references', ''),
        'list_unsubscribe': headers.get('list-unsubscribe', ''),
        'list_unsubscribe_post': headers.get('list-unsubscribe-post', ''),
    }


def strip_html(html: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


def attachments(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{'name': item.get('name') or item.get('filename') or '',
             'size': item.get('size', 0),
             'content_type': item.get('contentType') or item.get('content_type') or ''} for item in items]
