"""Apply incremental provider changes to the local inbox index."""

import imaplib
import logging

import httpx
from db.accessors import mail_account as account_access
from db.accessors import mail_message as message_access
from db.accessors import mail_sync_state as sync_state_access
from env.mail import env as mail_env

from api.mail import connectors, netguard, providers, secrets, service, sync_connector, sync_gmail, sync_graph, sync_imap, transport
from api.mail.sync_types import SyncResult

logger = logging.getLogger(__name__)


def _error_code(error: Exception) -> str:
    if isinstance(error, secrets.WorkspaceSecretNotFoundError):
        return "secret_not_found"
    if isinstance(error, service.CredentialError):
        return "auth_expired"
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
        return "auth_expired"
    if isinstance(error, (transport.MailHostNotAllowedError, netguard.BlockedAddressError)):
        return "host_not_allowed"
    if isinstance(error, (OSError, TimeoutError, imaplib.IMAP4.abort, httpx.TimeoutException, httpx.ConnectError)):
        return "unreachable"
    return "provider_error"


async def sync_account(account_id: str) -> SyncResult:
    account = await account_access.get_account(account_id)
    if account is None:
        raise LookupError(f"no mail account with id {account_id}")
    previous = await sync_state_access.get_state(account_id)
    cursor = previous.cursor if previous else ""
    await sync_state_access.save_state(account_id=account_id, cursor=cursor, status="syncing")
    try:
        if account.auth_type == connectors.CONNECTOR:
            provider = sync_connector
        elif account.provider == providers.IMAP:
            provider = sync_imap
        elif account.provider == providers.GOOGLE:
            provider = sync_gmail
        elif account.provider == providers.MICROSOFT:
            provider = sync_graph
        else:
            raise ValueError("Unknown provider")
        changes = await provider.fetch_changes(
            account, cursor=cursor,
            folders=[f.strip().upper() for f in mail_env.mail_sync_folders.split(",") if f.strip()],
            limit=mail_env.mail_sync_page_size, max_body_chars=mail_env.mail_sync_max_body_chars,
        )
        known = await message_access.known_uids(account_id, "INBOX")
        if changes.full_rebuild:
            await message_access.delete_folder(account_id, "INBOX")
        new_ids = []
        for parsed in changes.upserts:
            row = await message_access.upsert_message(account_id=account_id, **parsed)
            if parsed["provider_uid"] not in known:
                new_ids.append(row.id)
            if changes.full_rebuild:
                known[parsed["provider_uid"]] = row.id
        moved = set(changes.moved_out)
        for uid in set(changes.read_updates) | set(changes.flag_updates) | moved:
            if uid not in known:
                continue
            updates = {}
            if uid in changes.read_updates:
                updates["is_read"] = changes.read_updates[uid]
            if uid in changes.flag_updates:
                updates["is_flagged"] = changes.flag_updates[uid]
            if uid in moved:
                updates["folder"] = "ARCHIVE"
            await message_access.set_state(known[uid], **updates)
        await sync_state_access.save_state(account_id=account_id, cursor=changes.cursor, status="ok", last_error="")
        return SyncResult("ok", len(changes.upserts), changes.cursor, "", new_ids)
    except Exception as error:  # noqa: BLE001 — provider failures must not expose credentials
        code = _error_code(error)
        logger.warning("%s", type(error).__name__)
        await sync_state_access.save_state(account_id=account_id, cursor=cursor, status="error", last_error=code)
        return SyncResult("error", 0, cursor, code)
