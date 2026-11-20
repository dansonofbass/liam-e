"""Accessor for ``mail_sync_state`` rows: one sync-progress row per account."""

from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select, text
from db.accessors import user_preference

from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.mail_sync_state import MailSyncState


async def get_state(account_id: str) -> MailSyncState | None:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailSyncState).where(MailSyncState.account_id == account_id)
        )
        return result.scalar_one_or_none()


async def list_for_accounts(account_ids: list[str]) -> list[MailSyncState]:
    """Read stored sync progress for the authorized accounts only."""
    async with get_session_maker()() as session:
        result = await session.execute(select(MailSyncState).where(MailSyncState.account_id.in_(account_ids)))
        return list(result.scalars().all())


async def save_state(
    *,
    account_id: str,
    cursor: str | None = "",
    status: str = "ok",
    last_error: str = "",
    last_sync_at: datetime | None = None,
    connector_verified: bool | None = None,
    connector_cursor: str | None = None,
) -> MailSyncState:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailSyncState).where(MailSyncState.account_id == account_id)
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = MailSyncState(account_id=account_id)
        if connector_verified is not None:
            state.connector_verified = connector_verified
        if connector_cursor is not None:
            state.connector_cursor = connector_cursor
        if cursor is not None:
            state.cursor = cursor
        state.status = status
        state.last_error = last_error
        state.last_sync_at = last_sync_at if last_sync_at is not None else utcnow()
        state.updated_at = utcnow()
        session.add(state)
        await session.commit()
        return state


async def delete_for_account(account_id: str) -> None:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailSyncState).where(MailSyncState.account_id == account_id)
        )
        for state in result.scalars().all():
            await session.delete(state)
        await session.commit()


class StaleConnectorSync(Exception):
    """Another verified batch or an identity change has superseded this read."""


@asynccontextmanager
async def connector_transaction(account_id: str, previous: MailSyncState | None, *, verified: bool):
    """Fence publication against concurrent syncs, account removal and grant invalidation."""
    from db.models.mail_account import MailAccount
    async with get_session_maker().begin() as session:
        await user_preference.lock(session)
        state = (await session.execute(select(MailSyncState).where(
            MailSyncState.account_id == account_id).with_for_update())).scalar_one_or_none()
        generation = previous.connector_generation if previous else 0
        progress = previous.connector_cursor if previous else ""
        if (state is None or state.connector_generation != generation or state.connector_cursor != progress
                or await session.get(MailAccount, account_id) is None):
            raise StaleConnectorSync
        if verified:
            await session.execute(text("SELECT set_config('liam.verified_connector', :account, true)"), {'account': account_id})
        yield session, state
