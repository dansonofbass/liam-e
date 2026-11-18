"""Private feed configuration access inside caller-owned transactions."""

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.calendar_feed_config import CalendarFeedConfig


async def get(session: AsyncSession, source_id: str) -> CalendarFeedConfig | None:
    return await session.get(CalendarFeedConfig, source_id)


async def put(session: AsyncSession, *, source_id: str, encrypted_payload: str) -> None:
    row = await get(session, source_id)
    if row is None:
        row = CalendarFeedConfig(source_id=source_id, encrypted_payload=encrypted_payload)
    else:
        row.encrypted_payload = encrypted_payload
    session.add(row)
    await session.flush()
