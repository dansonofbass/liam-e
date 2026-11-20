"""Apply incremental provider changes to the local inbox index."""

import imaplib
import logging
from datetime import UTC, datetime, timedelta

import httpx
from db.accessors import mail_account as account_access
from db.accessors import mail_job
from db.accessors import mail_message as message_access
from db.accessors import mail_sync_state as sync_state_access
from env.mail import env as mail_env
from utils.mistral import MistralNotConfiguredError

from api.mail import connector_mailbox, connectors, netguard, providers, secrets, service, sync_connector, sync_gmail, sync_graph, sync_imap, transport
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
    if isinstance(error, (service.CredentialError, connector_mailbox.MailboxUnavailable)):
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
    is_connector = account.auth_type == connectors.CONNECTOR
    if is_connector and not is_seed_account(account_id):
        previous = await sync_state_access.save_state(account_id=account_id, cursor=None, status="syncing", claim_connector=True)
    else:
        previous = await sync_state_access.get_state(account_id)
    cursor = previous.cursor if previous else ""
    if is_seed_account(account_id):
        return SyncResult("ok", 0, cursor, "")
    if not is_connector:
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
        options = dict(folders=[f.strip().upper() for f in mail_env.mail_sync_folders.split(",") if f.strip()],
                       limit=mail_env.mail_sync_page_size, max_body_chars=mail_env.mail_sync_max_body_chars)
        verified = is_connector and not connector_mailbox.inbox_only(account)
        if verified:
            verified_cursor = previous.connector_cursor if previous and previous.connector_verified else ""
            generation = previous.connector_generation if previous else 0
            async with connector_mailbox.bound_mailbox(account, cursor=verified_cursor, generation=generation, observed=previous, bootstrap=True, check_after=True) as (binding, progress):
                changes, deferred = await _connector_changes(account, progress,
                    previous.connector_deferred_threads if previous.connector_verified else [], options)
            stored_progress = connector_mailbox.encode(binding, changes.cursor)
        elif is_connector:
            changes, deferred = await _connector_changes(account, previous.connector_cursor or cursor,
                previous.connector_deferred_threads, options)
            stored_progress = changes.cursor
        else:
            changes = await provider.fetch_changes(account, cursor=cursor, **options)
            stored_progress = changes.cursor
        if is_connector:
            async with sync_state_access.connector_transaction(account_id, previous, verified=verified) as (session, state):
                new_ids, invalidated = await _apply_changes(account_id, changes, unverified=not verified, connector_session=session)
                state.connector_deferred_threads = deferred
                if verified:
                    state.connector_proof_revision += 1
                    mail_job.queue_verified_insights(session, account_id, invalidated, mail_env.mail_insight_batch_limit)
                if verified and not state.connector_verified:
                    state.connector_generation += 1
                state.connector_verified = verified
                state.connector_cursor = stored_progress
                state.cursor = sync_connector.incremental_cursor(changes.cursor)
                state.status, state.last_error = "ok", ""
                state.last_sync_at = state.updated_at = datetime.now(UTC)
        else:
            new_ids, invalidated = await _apply_changes(account_id, changes, unverified=False)
            await sync_state_access.save_state(account_id=account_id, cursor=changes.cursor, status="ok", last_error="")
        try:
            reread = await refresh_bodies(account, provider)
        except (connector_mailbox.MailboxUnavailable, sync_state_access.StaleConnectorSync):
            raise
        except Exception as error:  # noqa: BLE001 — keep the completed page and retry body refresh
            logger.warning("Body refresh failed: %s", type(error).__name__)
            reread = []
        return SyncResult("ok", len(changes.upserts), stored_progress, "", new_ids, bool(invalidated or reread) and not verified)
    except sync_state_access.StaleConnectorSync:
        return SyncResult("error", 0, cursor, "provider_error")
    except Exception as error:  # noqa: BLE001 — provider failures must not expose credentials
        code = _error_code(error)
        logger.warning("%s", type(error).__name__)
        if is_connector:
            await sync_state_access.fail_connector(account_id, previous, code)
        else:
            await sync_state_access.save_state(account_id=account_id, cursor=cursor, status="error", last_error=code)
        return SyncResult("error", 0, cursor, code)


async def _connector_changes(account, progress, deferred, options):
    changes = await sync_connector.fetch_changes(account, cursor=progress, **options)
    retry_count = min(5, len(deferred))
    if retry_count:
        recovered = await sync_connector.retry_threads(account, deferred[:retry_count], options["max_body_chars"])
        sync_connector.merge_observations(changes, recovered)
    excluded = set(changes.moved_out) | changes.unconfirmed_uids
    changes.upserts = [row for row in changes.upserts if row["provider_uid"] not in excluded]
    return changes, list(dict.fromkeys([*deferred[retry_count:], *changes.deferred_threads]))


async def _apply_changes(account_id, changes, *, unverified, connector_session=None):
    transaction = {"session": connector_session} if connector_session is not None else {}
    invalidated = []
    known = await message_access.known_uids(account_id, "INBOX", **transaction)
    moved = set(changes.moved_out)
    if connector_session is not None:
        await message_access.reconcile_connector_folders(
            connector_session, account_id, {row["provider_uid"] for row in changes.upserts}, moved)
    # Rows this run rewrites that still hold text from an older extraction.
    old_texts = {} if changes.full_rebuild else await message_access.stale_body_texts(account_id, "INBOX", BODY_VERSION, [parsed["provider_uid"] for parsed in changes.upserts], **transaction)
    if changes.full_rebuild:
        await message_access.delete_folder(account_id, "INBOX")
    new_ids = []
    for parsed in changes.upserts:
        uid = parsed["provider_uid"]
        if connector_session is not None:
            if uid in changes.read_updates:
                parsed["is_read"] = changes.read_updates[uid]
            if uid in changes.flag_updates:
                parsed["is_flagged"] = changes.flag_updates[uid]
        outdated = uid in old_texts and insight_outdated(old_texts[uid], parsed["body_text"])
        row = await message_access.upsert_message(account_id=account_id, **parsed, body_version=BODY_VERSION, drop_insight=outdated,
                                                  unverified_connector=unverified, invalidated_insights=invalidated, **transaction)
        if uid not in known:
            new_ids.append(row.id)
        if changes.full_rebuild or connector_session is not None:
            known[parsed["provider_uid"]] = row.id
    for uid in set(changes.read_updates) | set(changes.flag_updates) | moved:
        if uid not in known:
            continue
        updates = {}
        if uid in changes.read_updates:
            updates["is_read"] = changes.read_updates[uid]
        if uid in changes.flag_updates:
            updates["is_flagged"] = changes.flag_updates[uid]
        if uid in moved and connector_session is None:
            updates["folder"] = "ARCHIVE"
        if updates:
            if connector_session is not None:
                updates["connector_labels"] = True
            await message_access.set_state(known[uid], **updates, **transaction)
    return new_ids, invalidated


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
    if account.auth_type == connectors.CONNECTOR and not connector_mailbox.inbox_only(account):
        state = await sync_state_access.get_state(account.id)
        if state is None or not state.connector_verified:
            raise connector_mailbox.MailboxUnavailable()
        async with connector_mailbox.bound_mailbox(account, cursor=state.connector_cursor, generation=state.connector_generation, observed=state, check_after=True):
            found = await provider.fetch_bodies(account, stale, max_body_chars=mail_env.mail_sync_max_body_chars)
        async with sync_state_access.connector_transaction(account.id, state, verified=True) as (session, _):
            dropped = await _apply_bodies(stale, found, now, session=session)
            mail_job.queue_verified_insights(session, account.id, dropped, mail_env.mail_insight_batch_limit)
            return dropped
    found = await provider.fetch_bodies(account, stale, max_body_chars=mail_env.mail_sync_max_body_chars)
    return await _apply_bodies(stale, found, now)


async def _apply_bodies(stale, found, now, *, session=None):
    transaction = {"session": session} if session is not None else {}
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
            await message_access.set_body(message.id, body_version=BODY_VERSION, drop_insight=outdated, **transaction)
        else:
            await message_access.set_body(message.id, body_version=BODY_VERSION, body_text=text, snippet=parsed["snippet"], drop_insight=outdated, **transaction)
    return dropped
