"""Calendar source storage."""

from sqlalchemy import delete, select

from db.engine import get_session_maker
from db.models.calendar_source import CalendarSource
from db.models.calendar_event import CalendarEvent
from db.models.calendar_feed_config import CalendarFeedConfig
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_sync_state import CalendarSyncState


async def get(source_id: str) -> CalendarSource | None:
    async with get_session_maker()() as session:
        return await session.get(CalendarSource, source_id)


async def list_all() -> list[CalendarSource]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(CalendarSource).order_by(CalendarSource.id))).scalars())


async def set_active(source_id: str, active: bool) -> CalendarSource | None:
    async with get_session_maker()() as session:
        row = (await session.execute(select(CalendarSource).where(CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if row is not None:
            if row.is_active != active:
                row.revision += 1
            row.is_active = active
            await session.commit()
        return row


async def remove(source_id: str) -> bool:
    async with get_session_maker()() as session:
        row = (await session.execute(select(CalendarSource).where(CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if row is None:
            return False
        for model in (CalendarOccurrence, CalendarEvent, CalendarSyncState, CalendarFeedConfig):
            await session.execute(delete(model).where(model.source_id == source_id))
        await session.delete(row)
        await session.commit()
        return True


async def list_active() -> list[CalendarSource]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(CalendarSource).where(CalendarSource.is_active.is_(True)).order_by(CalendarSource.id))).scalars())
