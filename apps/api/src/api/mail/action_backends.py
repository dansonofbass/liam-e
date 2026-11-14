"""Provider mutations; callers retain the pre-action index snapshot for undo."""

import asyncio
import imaplib
import json
import re
from typing import Protocol
from urllib.parse import quote

import httpx
from db.models.mail_account import MailAccount
from db.models.mail_message import MailMessage

from api.mail import connectors, providers, service, transport
from api.mail.actions import ActionKind, ActionUnsupportedError, write_connector_labels
from api.mail.seed_ids import is_seed_account


class ProviderBackend(Protocol):
    async def apply(self, message: MailMessage, kind: ActionKind) -> dict: ...
    async def revert(self, message: MailMessage, previous: dict) -> dict: ...


def backend_for(account: MailAccount) -> ProviderBackend:
    if is_seed_account(account.id):
        return IndexBackend()
    if account.auth_type == connectors.CONNECTOR:
        return LabelBackend(account, connector=True)
    if account.provider == providers.IMAP:
        return ImapBackend(account)
    if account.provider == providers.GOOGLE:
        return LabelBackend(account)
    if account.provider == providers.MICROSOFT:
        return GraphBackend(account)
    raise ActionUnsupportedError()


class IndexBackend:
    async def apply(self, message: MailMessage, kind: ActionKind) -> dict:
        return {}

    async def revert(self, message: MailMessage, previous: dict) -> dict:
        return {}


async def _headers(account: MailAccount) -> dict[str, str]:
    credentials = await service.load_credentials(account)
    return {"Authorization": f"Bearer {await service.valid_access_token(account, credentials)}"}


class LabelBackend:
    def __init__(self, account: MailAccount, *, connector: bool = False):
        self.account = account
        self.connector = connector

    async def apply(self, message: MailMessage, kind: ActionKind) -> dict:
        # Folder state remains authoritative even if a connector omitted labels.
        current = set(json.loads(message.labels_json))
        if message.folder == "INBOX":
            current.add("INBOX")
        if message.folder == "TRASH":
            current.add("TRASH")
        if kind == "archive":
            desired = sorted(current - {"INBOX"})
        elif kind == "trash":
            desired = sorted((current - {"INBOX"}) | {"TRASH"})
        elif kind == "restore":
            desired = sorted((current - {"TRASH"}) | {"INBOX"} | (set() if message.is_read else {"UNREAD"}))
        elif kind == "mark_read":
            current.add("UNREAD")
            desired = sorted(current - {"UNREAD"})
        else:
            current.discard("UNREAD")
            desired = sorted(current | {"UNREAD"})
        return await self._change(message, current, set(desired), kind=kind)

    async def revert(self, message: MailMessage, previous: dict) -> dict:
        current = set(json.loads(message.labels_json))
        desired = set(json.loads(previous["labels_json"]))
        desired.difference_update({"INBOX", "TRASH", "UNREAD"})
        if previous["folder"] in ("INBOX", "TRASH"):
            desired.add(previous["folder"])
        if not previous["is_read"]:
            desired.add("UNREAD")
        await self._change(message, current, desired)
        return {"labels_json": previous["labels_json"]}

    async def _change(self, message: MailMessage, current: set[str], desired: set[str], *, kind: ActionKind | None = None) -> dict:
        added, removed = sorted(desired - current), sorted(current - desired)
        if self.connector:
            await write_connector_labels(self.account.provider, message.provider_uid, added=added, removed=removed)
        else:
            headers = await _headers(self.account)
            path = f"/messages/{quote(message.provider_uid, safe='')}"
            async with httpx.AsyncClient(timeout=30, base_url=providers.GMAIL_API, headers=headers) as client:
                if kind == "trash" or ("TRASH" in added):
                    response = await client.post(path + "/trash")
                    response.raise_for_status()
                    return {"labels_json": json.dumps(sorted(desired))}
                elif "TRASH" in removed or (kind == "restore" and message.folder == "TRASH"):
                    response = await client.post(path + "/untrash")
                    response.raise_for_status()
                # TRASH is managed by its dedicated endpoints, not modify.
                added = [label for label in added if label != "TRASH"]
                removed = [label for label in removed if label != "TRASH"]
                if added or removed:
                    response = await client.post(path + "/modify", json={"addLabelIds": added, "removeLabelIds": removed})
                    response.raise_for_status()
        return {"labels_json": json.dumps(sorted(desired))}


class GraphBackend:
    def __init__(self, account: MailAccount):
        self.account = account

    async def _change(self, message: MailMessage, *, folder: str | None = None, is_read: bool | None = None) -> dict:
        headers = await _headers(self.account)
        uid = message.provider_uid
        updates = {}
        async with httpx.AsyncClient(timeout=30, base_url=providers.GRAPH_API, headers=headers) as client:
            if is_read is not None:
                response = await client.patch(f"/me/messages/{quote(uid, safe='')}", json={"isRead": is_read})
                response.raise_for_status()
            if folder is not None and folder != message.folder:
                destination = {"INBOX": "inbox", "ARCHIVE": "archive", "TRASH": "deleteditems"}.get(folder)
                if destination is None:
                    raise ActionUnsupportedError()
                response = await client.post(f"/me/messages/{quote(uid, safe='')}/move", json={"destinationId": destination})
                response.raise_for_status()
                uid = response.json()["id"]
                if not isinstance(uid, str) or not uid:
                    raise RuntimeError("Missing Graph message id")
                updates["provider_uid"] = uid
        return updates

    async def apply(self, message: MailMessage, kind: ActionKind) -> dict:
        if kind in ("mark_read", "mark_unread"):
            return await self._change(message, is_read=kind == "mark_read")
        return await self._change(message, folder={"archive": "ARCHIVE", "trash": "TRASH", "restore": "INBOX"}[kind])

    async def revert(self, message: MailMessage, previous: dict) -> dict:
        updates = await self._change(message, folder=previous["folder"], is_read=previous["is_read"])
        # An earlier move's snapshot ID is no longer valid, even for read-only undo.
        return {"provider_uid": message.provider_uid} | updates


def _quoted(value: str) -> str:
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise ActionUnsupportedError()
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _ok(result):
    status, data = result
    if status != "OK":
        raise RuntimeError("IMAP command failed")
    return data


def _folder(folder: str, listing: list) -> str:
    if folder == "INBOX":
        return "INBOX"
    special = {"ARCHIVE": "\\archive", "TRASH": "\\trash"}.get(folder)
    if special is None:
        raise ActionUnsupportedError()
    parsed = []
    for line in listing:
        if not isinstance(line, bytes):
            continue
        match = re.match(r'\(([^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(.+)$', line.decode())
        if not match:
            continue
        flags, name = match.groups()
        if name.startswith('"') and name.endswith('"'):
            name = re.sub(r'\\(.)', r'\1', name[1:-1])
        if "\\noselect" not in flags.lower().split():
            parsed.append((flags.lower().split(), name))
    for flags, name in parsed:
        if special in flags:
            return name
    for fallback in {"ARCHIVE": ("Archive", "Archiv"), "TRASH": ("Trash", "Papierkorb", "Deleted Items")}[folder]:
        if any(name == fallback for _, name in parsed):
            return fallback
    raise ActionUnsupportedError()


def _search(connection, message: MailMessage) -> str:
    if not message.rfc_message_id:
        raise ActionUnsupportedError()
    data = _ok(connection.uid("SEARCH", None, "HEADER", "Message-ID", _quoted(message.rfc_message_id)))
    uids = data[0].split() if data and data[0] else []
    if len(uids) != 1 or not uids[0].isdigit():
        raise RuntimeError("IMAP message not uniquely found")
    return uids[0].decode()


class ImapBackend:
    def __init__(self, account: MailAccount):
        self.account = account

    async def apply(self, message: MailMessage, kind: ActionKind) -> dict:
        folder = {"archive": "ARCHIVE", "trash": "TRASH", "restore": "INBOX"}.get(kind, message.folder)
        is_read = kind == "mark_read" if kind in ("mark_read", "mark_unread") else None
        return await self._run(message, folder, is_read, undo=False)

    async def revert(self, message: MailMessage, previous: dict) -> dict:
        return await self._run(message, previous["folder"], previous["is_read"], undo=True)

    async def _run(self, message: MailMessage, folder: str, is_read: bool | None, *, undo: bool) -> dict:
        credentials = await service.load_credentials(self.account)
        host = credentials["imap_host"]
        await transport.check_mail_host(host)
        password = await service.imap_password(credentials)
        return await asyncio.to_thread(self._change, host, int(credentials.get("imap_port", 993)), password, message, folder, is_read, undo)

    def _change(self, host: str, port: int, password: str, message: MailMessage, folder: str, is_read: bool | None, undo: bool) -> dict:
        connection = transport.open_imap(host, port)
        try:
            _ok(connection.login(self.account.email_address, password))
            listing = _ok(connection.list('""', '"*"')) if message.folder != "INBOX" or folder != "INBOX" else []
            source = _folder(message.folder, listing)
            target = _folder(folder, listing)
            capabilities = {value.decode().upper() if isinstance(value, bytes) else value.upper() for value in connection.capabilities}
            moving = source != target
            if moving and "MOVE" not in capabilities and "UIDPLUS" not in capabilities:
                # Never expunge unrelated deleted messages on servers without UID EXPUNGE.
                raise ActionUnsupportedError()
            if moving and not message.rfc_message_id:
                # Undo must be able to locate the message after its folder UID changes.
                raise ActionUnsupportedError()
            _ok(connection.select(_quoted(source)))
            # The stored UID is only valid while the row is in INBOX; elsewhere it may be stale.
            uid = message.provider_uid if message.folder == "INBOX" else _search(connection, message)
            if not uid.isdigit():
                raise ActionUnsupportedError()
            if is_read is not None:
                _ok(connection.uid("STORE", uid, "+FLAGS" if is_read else "-FLAGS", "(\\Seen)"))
            inbox_uid = message.provider_uid
            if moving:
                _ok(connection.uid("MOVE" if "MOVE" in capabilities else "COPY", uid, _quoted(target)))
                _, copy_data = connection.response("COPYUID")
                copied_uid = None
                if copy_data and isinstance(copy_data[0], bytes):
                    match = re.fullmatch(rb"\d+ \d+ (\d+)", copy_data[0])
                    if match:
                        copied_uid = match.group(1).decode()
                if "MOVE" not in capabilities:
                    _ok(connection.uid("STORE", uid, "+FLAGS", "(\\Deleted)"))
                    _ok(connection.uid("EXPUNGE", uid))
                if folder == "INBOX":
                    if copied_uid is not None:
                        inbox_uid = copied_uid
                    else:
                        _ok(connection.select(_quoted(target)))
                        inbox_uid = _search(connection, message)
            # Outside INBOX the index retains its former INBOX UID, like sync.
            return {"provider_uid": inbox_uid}
        finally:
            try:
                connection.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
