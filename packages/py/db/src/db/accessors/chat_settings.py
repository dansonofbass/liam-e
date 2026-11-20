"""The installed owner's chat grants, serialized with turn creation and proposal claims."""
import json

from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from db.accessors import user_preference
from db.accessors.prompt_template import StaleVersion
from db.engine import get_session_maker
from db.models.chat_context import ChatContext
from db.models.chat_settings import ChatSettings
from db.models.mail_account import MailAccount
from db.models.mail_message import MailMessage
from db.models.mail_insight import MailInsight
from db.models.mail_sync_state import CONNECTOR_CURSOR_PREFIX, MailSyncState
from db.models.prompt_template import OWNER_SCOPE


class GrantsChanged(Exception):
    pass


class AccountNotGranted(ValueError):
    pass


async def in_session(session: AsyncSession) -> ChatSettings:
    return await session.get(ChatSettings, OWNER_SCOPE) or ChatSettings()


async def get() -> ChatSettings:
    async with get_session_maker()() as session:
        return await in_session(session)


async def active_ids(session: AsyncSession, account_ids: list[str]) -> list[str]:
    if not account_ids:
        return []
    # Pre-binding connector indexes may contain mail fetched from a different default mailbox.
    verified_index = select(MailSyncState.id).where(MailSyncState.account_id == MailAccount.id,
        MailSyncState.connector_verified.is_(True), MailSyncState.connector_cursor.startswith(CONNECTOR_CURSOR_PREFIX)).exists()
    query = select(MailAccount.id).where(MailAccount.id.in_(account_ids), MailAccount.is_active.is_(True),
        (MailAccount.auth_type != 'mistral_connector') | verified_index)
    return sorted((await session.execute(query)).scalars())


async def update(expected_version: int, account_ids: list[str]) -> ChatSettings:
    ids = sorted(set(account_ids))
    async with get_session_maker()() as session:
        await user_preference.lock(session)
        row = await in_session(session)
        if row.version != expected_version:
            raise StaleVersion
        if ids != await active_ids(session, ids):
            raise AccountNotGranted
        if ids != row.account_ids:
            row.account_ids = ids
            row.version += 1
            session.add(row)
        await session.commit()
        return row


async def remove_account(session: AsyncSession, account_id: str) -> None:
    """The caller owns the same grant lock and the account deletion transaction."""
    row = await in_session(session)
    if account_id in row.account_ids:
        row.account_ids = [item for item in row.account_ids if item != account_id]
        row.version += 1
        session.add(row)


async def permits_context(session: AsyncSession, context: ChatContext | None) -> bool:
    """Old turns have no verified central grant. Stored messages remain readable by the owner."""
    if context is None or context.mail_scope_version is None:
        return False
    settings = await in_session(session)
    if settings.version != context.mail_scope_version:
        return False
    try:
        scope = json.loads(context.account_scope_json)
    except (TypeError, ValueError):
        return False
    if not isinstance(scope, dict) or "selection" not in scope:
        return False
    focus = scope["selection"]
    ids = await active_ids(session, settings.account_ids)
    if focus is not None:
        return focus in ids and scope.get("account_ids") == [focus]
    return scope.get("account_ids") == ids


async def mail_preview(message_id: str, version: int | None, context_id: str | None) -> tuple[MailMessage, MailInsight | None] | None:
    """Retrieve a live preview only within the current grant and optional stored turn focus."""
    async with get_session_maker()() as session:
        await user_preference.lock(session)
        settings = await in_session(session)
        if (version is None and context_id is None) or (version is not None and settings.version != version):
            return None
        ids = await active_ids(session, settings.account_ids)
        if context_id is not None:
            context = await session.get(ChatContext, context_id)
            if context is None or context.revoked or not await permits_context(session, context):
                return None
            ids = json.loads(context.account_scope_json)['account_ids']
        query = select(MailMessage, MailInsight).outerjoin(MailInsight, MailInsight.message_id == MailMessage.id).where(
            MailMessage.id == message_id, MailMessage.account_id.in_(ids), MailMessage.unverified_connector.is_(False))
        return (await session.execute(query)).tuples().one_or_none()


async def invalidate_connector(account_id: str, generation: int | None = None) -> None:
    """A lost mailbox proof withdraws the grant and blocks reselection until a verified sync."""
    async with get_session_maker()() as session:
        await user_preference.lock(session)
        state = (await session.execute(select(MailSyncState).where(
            MailSyncState.account_id == account_id).with_for_update())).scalar_one_or_none()
        if state is not None:
            if generation is not None and state.connector_generation != generation:
                return
            state.connector_generation += 1
            state.connector_verified = False
            await session.execute(sql_update(MailMessage).where(MailMessage.account_id == account_id).values(unverified_connector=True))
        await remove_account(session, account_id)
        await session.commit()
