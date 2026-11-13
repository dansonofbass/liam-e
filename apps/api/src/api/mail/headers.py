"""Utilities for mail address and unsubscribe headers."""

import re
from email import policy
from email.header import decode_header, make_header
from email.parser import Parser
from email.utils import parseaddr


def plain_address(address: str) -> str:
    if address.count("@") != 1 or "=?" in address:
        return ""
    local, domain = address.split("@")
    if not local or not domain or re.search(r"[\s<>\"(),;:\\]", address):
        return ""
    return address.lower()


def sender_address(from_header: str) -> str:
    try:
        structured = Parser(policy=policy.default).parsestr("From: " + from_header + "\n\n")["From"]
        if sum(bool(plain_address(item.addr_spec)) for item in structured.addresses) > 1:
            return ""
        address = plain_address(parseaddr(from_header)[1])
        if address:
            return address
        encoded_word = r"=\?[^?\s]+\?[bq]\?[^?]*\?="
        if any(re.search(r"<[^<>]*@[^<>]*>", word) for word in re.findall(encoded_word, from_header, re.IGNORECASE)):
            return ""
        cleaned = re.sub(encoded_word + r"|\"(?:\\.|[^\"\\])*\"", "", from_header, flags=re.IGNORECASE)
        candidates = [plain_address(value) for value in re.findall(r"<([^<>]+)>", cleaned)]
        candidates = [value for value in candidates if value]
        return candidates[0] if len(candidates) == 1 else ""
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
