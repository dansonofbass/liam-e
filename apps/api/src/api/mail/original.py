"""Fetch a capped original message from its provider without modifying it."""

import asyncio
import base64
import imaplib
import re
from email import policy
from email.parser import BytesParser
from urllib.parse import quote

import httpx

from api.mail import connectors, providers, service, transport
from api.mail.action_backends import _folder, _headers, _message_uid, _ok, _quoted, imap_locatable
from api.mail.actions import ActionUnsupportedError
from api.mail.seed_ids import is_seed_account

MAX_SOURCE_BYTES = 262_144


def available(account, message) -> bool:
    return bool(account and not is_seed_account(account.id) and account.auth_type != connectors.CONNECTOR
                and (account.provider in (providers.GOOGLE, providers.MICROSOFT)
                     or (account.provider == providers.IMAP and imap_locatable(message))))


def parse_headers(raw: bytes) -> list[dict[str, str]]:
    block = re.split(rb'\r?\n\r?\n', raw, maxsplit=1)[0]
    try:
        parsed = BytesParser(policy=policy.default).parsebytes(block + b'\r\n\r\n', headersonly=True)
        return [{"name": name, "value": str(value)} for name, value in parsed.items()]
    except Exception:
        return []


def _imap_fetch(account, message, host, port, password):
    connection = transport.open_imap(host, port)
    try:
        _ok(connection.login(account.email_address, password))
        listing = _ok(connection.list('""', '"*"')) if message.folder != "INBOX" else []
        folder = _folder(message.folder, listing)
        _ok(connection.select(_quoted(folder), readonly=True))
        uid = _message_uid(connection, message)
        if not uid.isdigit():
            raise ActionUnsupportedError()
        data = _ok(connection.uid("FETCH", uid, f"(RFC822.SIZE BODY.PEEK[]<0.{MAX_SOURCE_BYTES}>)"))
        body = next((item[1] for item in data if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes)), None)
        if body is None:
            raise RuntimeError("Missing IMAP message")
        # Servers may report the size before or after the body literal, so look at everything but the literal.
        parts = [item[0] if isinstance(item, tuple) else item for item in data]
        size = re.search(rb'RFC822\.SIZE\s+(\d+)', b" ".join(part for part in parts if isinstance(part, bytes)), re.I)
        return body[:MAX_SOURCE_BYTES], int(size.group(1)) > MAX_SOURCE_BYTES if size else len(body) >= MAX_SOURCE_BYTES
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


async def fetch(account, message):
    if not available(account, message):
        raise ActionUnsupportedError()
    if account.provider == providers.IMAP:
        credentials = await service.load_credentials(account)
        host = credentials["imap_host"]
        await transport.check_mail_host(host)
        password = await service.imap_password(credentials)
        raw, truncated = await asyncio.to_thread(_imap_fetch, account, message, host, int(credentials.get("imap_port", 993)), password)
    else:
        headers = await _headers(account)
        uid = quote(message.provider_uid, safe='')
        if account.provider == providers.GOOGLE:
            async with httpx.AsyncClient(timeout=30, base_url=providers.GMAIL_API, headers=headers) as client:
                path = f"/messages/{uid}"
                response = await client.get(path, params={"format": "minimal", "fields": "sizeEstimate"})
                response.raise_for_status()
                if response.json()["sizeEstimate"] > 1_048_576:
                    response = await client.get(path, params={"format": "metadata"})
                    response.raise_for_status()
                    entries = response.json().get("payload", {}).get("headers", [])
                    raw = b"\r\n".join((entry["name"] + ": " + entry["value"]).encode("utf-8") for entry in entries)[:MAX_SOURCE_BYTES]
                    truncated = True
                else:
                    response = await client.get(path, params={"format": "raw", "fields": "raw"})
                    response.raise_for_status()
                    encoded = response.json()["raw"]
                    decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                    raw, truncated = decoded[:MAX_SOURCE_BYTES], len(decoded) > MAX_SOURCE_BYTES
        else:
            async with httpx.AsyncClient(timeout=30, base_url=providers.GRAPH_API, headers=headers) as client:
                async with client.stream("GET", f"/me/messages/{uid}/$value") as response:
                    response.raise_for_status()
                    data = bytearray()
                    truncated = False
                    async for chunk in response.aiter_bytes():
                        remaining = MAX_SOURCE_BYTES - len(data)
                        data.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            truncated = True
                            break
                    raw = bytes(data)
    return {"headers": parse_headers(raw), "source": raw.decode("utf-8", errors="replace"), "truncated": truncated}
