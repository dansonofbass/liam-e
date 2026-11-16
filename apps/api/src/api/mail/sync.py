"""Apply incremental provider changes to the local inbox index."""

import imaplib
import logging
from datetime import UTC, datetime, timedelta

import httpx
from db.accessors import mail_account as account_access
from db.accessors import mail_message as message_access
from db.accessors import mail_sync_state as sync_state_access
from env.mail import env as mail_env
from utils.mistral import MistralNotConfiguredError

from api.mail import connectors, netguard, providers, secrets, service, sync_connector, sync_gmail, sync_graph, sync_imap, transport
from api.mail.seed_ids import is_seed_account
from api.mail.sync_types import BODY_VERSION, SyncResult

logger = logging.getLogger(__name__)
# Bodies re-read per run after the text extraction changed; a backlog drains over the next runs.
BODY_REFRESH_BATCH = 25
# Re-reads this process could not finish, by message id: failures so far and when to ask again. A few
# unreadable mails must neither hold up the rest of the list, which is read newest first, nor be asked
# for on every run: the wait doubles per failure, from an hour up to a day. A restart forgets it.
REREAD_WAIT = timedelta(hours=1)
REREAD_WAIT_MAX = timedelta(days=1)
_reread_backoff: dict[str, tuple[int, datetime]] = {}


def _error_code(error: Exception) -> str:
    if isinstance(error, secrets.WorkspaceSecretNotFoundError):
        return "secret_not_found"
    # The app's own Mistral access is missing or refused: no new provider login would help.
    if isinstance(error, MistralNotConfiguredError):
        return "mistral_not_configured"
    if isinstance(error, secrets.WorkspaceSecretAccessDeniedError):
        return "secret_access_denied"
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
    if is_seed_account(account_id):
        return SyncResult("ok", 0, cursor, "")
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
        # Rows this run rewrites that still hold text from an older extraction.
        previous = {} if changes.full_rebuild else await message_access.stale_body_texts(account_id, "INBOX", BODY_VERSION, [parsed["provider_uid"] for parsed in changes.upserts])
        if changes.full_rebuild:
            await message_access.delete_folder(account_id, "INBOX")
        new_ids = []
        for parsed in changes.upserts:
            uid = parsed["provider_uid"]
            outdated = uid in previous and insight_outdated(previous[uid], parsed["body_text"])
            row = await message_access.upsert_message(account_id=account_id, **parsed, body_version=BODY_VERSION, drop_insight=outdated)
            if uid not in known:
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
        try:
            await refresh_bodies(account, provider)
        except Exception as error:  # noqa: BLE001 — the sync itself succeeded; the next run retries
            logger.warning("Body refresh failed: %s", type(error).__name__)
        return SyncResult("ok", len(changes.upserts), changes.cursor, "", new_ids)
    except Exception as error:  # noqa: BLE001 — provider failures must not expose credentials
        code = _error_code(error)
        logger.warning("%s", type(error).__name__)
        await sync_state_access.save_state(account_id=account_id, cursor=cursor, status="error", last_error=code)
        return SyncResult("error", 0, cursor, code)


def insight_outdated(old_text: str, new_text: str) -> bool:
    """An insight summarizes the stored text: it goes when the text changes, and when there is no text
    at all (the model then only had the subject and made things up; without text none is computed)."""
    return new_text != old_text or not new_text.strip()


async def refresh_bodies(account, provider) -> list[str]:
    """Re-read INBOX bodies stored by an older text extraction; returns the ids whose insight was dropped."""
    now = datetime.now(UTC)
    waiting = [message_id for message_id, (_, retry_at) in _reread_backoff.items() if retry_at > now]
    stale = await message_access.stale_bodies(account.id, "INBOX", BODY_VERSION, limit=BODY_REFRESH_BATCH, exclude=waiting)
    if not stale:
        return []
    found = await provider.fetch_bodies(account, stale, max_body_chars=mail_env.mail_sync_max_body_chars)
    dropped = []
    for message in stale:
        if message.provider_uid not in found:
            failures = _reread_backoff.get(message.id, (0, now))[0] + 1
            _reread_backoff[message.id] = (failures, now + min(REREAD_WAIT * 2 ** min(failures - 1, 5), REREAD_WAIT_MAX))
            continue
        _reread_backoff.pop(message.id, None)
        parsed = found[message.provider_uid]
        # Another Message-ID means the provider id now names a different mail (renumbered IMAP UIDs).
        if parsed is not None and message.rfc_message_id and parsed.get("rfc_message_id") and parsed["rfc_message_id"] != message.rfc_message_id:
            parsed = None
        text = message.body_text if parsed is None else parsed["body_text"]
        outdated = insight_outdated(message.body_text, text)
        if outdated:
            dropped.append(message.id)
        if parsed is None:
            # Gone or not this mail: the stored text stays and the row is not asked for again.
            await message_access.set_body(message.id, body_version=BODY_VERSION, drop_insight=outdated)
        else:
            await message_access.set_body(message.id, body_version=BODY_VERSION, body_text=text, snippet=parsed["snippet"], drop_insight=outdated)
    return dropped