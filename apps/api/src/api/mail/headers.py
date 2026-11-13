"""Utilities for mail address and unsubscribe headers."""

import re
from email.header import decode_header, make_header
from email.utils import parseaddr


def sender_address(from_header: str) -> str:
    return parseaddr(str(make_header(decode_header(from_header))))[1].lower()


def sender_name(from_header: str) -> str:
    name, address = parseaddr(str(make_header(decode_header(from_header))))
    return name or address.split('@', 1)[0]


def parse_list_unsubscribe(value: str) -> list[str]:
    return re.findall(r'<([^<>]+)>', value)
