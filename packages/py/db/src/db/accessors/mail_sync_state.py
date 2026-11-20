"""Accessor for ``mail_sync_state`` rows: one sync-progress row per account."""

from datetime import datetime

from sqlalchemy import select

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
    cursor: str = "",
    status: str = "ok",
    last_error: str = "",
    last_sync_at: datetime | None = None,
    connector_verified: bool | None = None,
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
