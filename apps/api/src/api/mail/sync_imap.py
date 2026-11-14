"""Parse RFC 822 messages fetched over IMAP."""

import asyncio
import email
import imaplib
import json
import re
from datetime import UTC
from email import policy
from email.utils import parsedate_to_datetime
from typing import Any

from db.accessors import mail_message as message_access
from db.models.mail_account import MailAccount

from api.mail import service, transport
from api.mail.headers import sender_address
from api.mail.sync_types import SyncChanges, addresses, common


def _fetch(host: str, port: int, email_address: str, password: str, cursor: str, known: dict[str, str], limit: int, max_body_chars: int) -> SyncChanges:
    connection = transport.open_imap(host, port)
    try:
        try:
            connection.login(email_address, password)
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error as error:
            raise service.CredentialError("IMAP login rejected") from error
        status, _ = connection.select('"INBOX"', readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP select failed")
        _, values = connection.response("UIDVALIDITY")
        validity = values[0].decode() if values and values[0] else ""
        if not validity:
            raise RuntimeError("IMAP UIDVALIDITY missing")
        previous_validity, separator, previous_uid = cursor.partition(":")
        rebuild = not separator or previous_validity != validity or not previous_uid.isdigit()
        last = 0 if rebuild else int(previous_uid)
        status, data = connection.uid("search", None, "ALL" if rebuild else "UID", *(() if rebuild else (f"{last + 1}:*",)))
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        uids = sorted(int(uid) for uid in (data[0].split() if data and data[0] else []) if int(uid) > last)
        selected = uids[-limit:] if rebuild else uids[:limit]
        changes = SyncChanges(full_rebuild=rebuild, cursor=f"{validity}:{selected[-1] if selected else last}")
        if not rebuild and known:
            numeric = [int(uid) for uid in known if uid.isdigit()]
            if numeric:
                status, data = connection.uid("fetch", f"{min(numeric)}:{max(numeric)}", "(FLAGS)")
                if status != "OK":
                    raise RuntimeError("IMAP flags fetch failed")
                found = set()
                for entry in data or []:
                    raw = entry[0] if isinstance(entry, tuple) else entry
                    if not isinstance(raw, bytes):
                        continue
                    uid_match = re.search(rb"\bUID\s+(\d+)", raw, re.I)
                    flags_match = re.search(rb"\bFLAGS\s*\(([^)]*)\)", raw, re.I)
                    if uid_match and not flags_match:
                        raise RuntimeError("IMAP flags missing")
                    if not uid_match:
                        continue
                    uid = uid_match.group(1).decode()
                    if uid not in known:
                        continue
                    found.add(uid)
                    flags = flags_match.group(1).lower().split()
                    changes.read_updates[uid] = b"\\seen" in flags
                    changes.flag_updates[uid] = b"\\flagged" in flags
                changes.moved_out = [uid for uid in known if uid.isdigit() and uid not in found]
        for uid in selected:
            status, data = connection.uid("fetch", str(uid), "(UID FLAGS RFC822.SIZE BODY.PEEK[])")
            if status != "OK":
                raise RuntimeError("IMAP message fetch failed")
            part = next((entry for entry in data or [] if isinstance(entry, tuple) and entry[1]), None)
            if part is None:
                raise RuntimeError("IMAP message missing from fetch")
            flags_match = re.search(rb"\bFLAGS\s*\(([^)]*)\)", part[0], re.I)
            flags = flags_match.group(1).lower().split() if flags_match else []
            parsed = parse_rfc822(part[1], max_body_chars=max_body_chars)
            parsed.update(folder="INBOX", provider_uid=str(uid), is_read=b"\\seen" in flags, is_flagged=b"\\flagged" in flags)
            changes.upserts.append(parsed)
        return changes
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


async def fetch_changes(account: MailAccount, *, cursor: str, folders: list[str], limit: int, max_body_chars: int) -> SyncChanges:
    credentials = await service.load_credentials(account)
    host = credentials["imap_host"]
    await transport.check_mail_host(host)
    password = await service.imap_password(credentials)
    known = await message_access.known_uids(account.id, "INBOX") if cursor else {}
    return await asyncio.to_thread(_fetch, host, int(credentials.get("imap_port", 993)), account.email_address, password, cursor, known, limit, max_body_chars)


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
    reply_to_addresses = mailbox_addresses("reply-to")
    return {**sender_fields, "thread_id": hdr.get("message-id", ""),
            "subject": header("subject"), "sender": sender,
            "recipients_json": json.dumps(to_addresses) if to_addresses is not None else addresses(header("to")),
            "cc_json": json.dumps(cc_addresses) if cc_addresses is not None else addresses(header("cc")),
            "reply_to_json": json.dumps(reply_to_addresses) if reply_to_addresses is not None else addresses(header("reply-to")),
            'snippet': ' '.join(body.split())[:500], 'body_text': body,
            'internal_date': date, 'has_attachments': bool(files),
            'attachments_json': json.dumps(files), 'is_read': False,
            'is_flagged': False, 'labels_json': '[]'}
