"""Utilities for mail address and unsubscribe headers."""

import re
from email.header import decode_header, make_header
from email.utils import parseaddr


def sender_address(from_header: str) -> str:
    try:
        address = parseaddr(from_header)[1]
        if not address:
            candidates = re.findall(r"<([^<>\s]+@[^<>\s]+)>", from_header)
            address = candidates[-1] if candidates else ""
        return "" if "=?" in address else address.lower()
    except Exception:
        return ""


def sender_name(from_header: str) -> str:
    try:
        name = parseaddr(from_header)[0]
        if not name:
            return sender_address(from_header).split("@", 1)[0]
        try:
            return str(make_header(decode_header(name)))
        except Exception:
            return name
    except Exception:
        return ""


def parse_list_unsubscribe(value: str) -> list[str]:
    return re.findall(r'<([^<>]+)>', value)
