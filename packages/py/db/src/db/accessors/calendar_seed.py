"""Replace only deterministic local calendar fixture rows."""

from sqlalchemy import delete

from db.engine import get_session_maker
from db.models.calendar_source import CalendarSource
from db.models.calendar_event import CalendarEvent
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_sync_state import CalendarSyncState


async def replace(sources: list[CalendarSource], events: list[CalendarEvent],
                  occurrences: list[CalendarOccurrence], states: list[CalendarSyncState]) -> None:
    ids = [source.id for source in sources]
    async with get_session_maker()() as session:
        for model in (CalendarOccurrence, CalendarEvent, CalendarSyncState):
            await session.execute(delete(model).where(model.source_id.in_(ids)))
        await session.execute(delete(CalendarSource).where(CalendarSource.id.in_(ids)))
        session.add_all([*sources, *events, *occurrences, *states])
        await session.commit()
