"""The installed owner's chat grants, serialized with turn creation and proposal claims."""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.accessors import user_preference
from db.accessors.prompt_template import StaleVersion
from db.engine import get_session_maker
from db.models.chat_context import ChatContext
from db.models.chat_settings import ChatSettings
from db.models.mail_account import MailAccount
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
    query = select(MailAccount.id).where(MailAccount.id.in_(account_ids), MailAccount.is_active.is_(True))
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
