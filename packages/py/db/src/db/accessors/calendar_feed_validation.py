"""One-time proof consumption; callers own the subscription transaction."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.calendar_feed_validation import CalendarFeedValidation


async def consume(session: AsyncSession, *, token_digest: str, context_id: str,
                  config_digest: str, now: datetime) -> CalendarFeedValidation | None:
    # DELETE RETURNING serializes competing consumers without a read/write gap.
    return (await session.execute(delete(CalendarFeedValidation).where(
        CalendarFeedValidation.token_digest == token_digest,
        CalendarFeedValidation.context_id == context_id,
        CalendarFeedValidation.config_digest == config_digest,
        CalendarFeedValidation.expires_at > now,
    ).returning(CalendarFeedValidation))).scalar_one_or_none()


async def purge_expired(session: AsyncSession, *, now: datetime) -> None:
    await session.execute(delete(CalendarFeedValidation).where(CalendarFeedValidation.expires_at <= now))


async def add(session: AsyncSession, row: CalendarFeedValidation) -> None:
    session.add(row)
    await session.flush()


async def discard(session: AsyncSession, *, token_digest: str, context_id: str) -> None:
    await session.execute(delete(CalendarFeedValidation).where(
        CalendarFeedValidation.token_digest == token_digest, CalendarFeedValidation.context_id == context_id))
