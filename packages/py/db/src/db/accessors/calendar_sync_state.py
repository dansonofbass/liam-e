"""Persistent calendar sync state lookups."""

from db.engine import get_session_maker
from db.models.calendar_sync_state import CalendarSyncState


async def get(source_id: str) -> CalendarSyncState | None:
    async with get_session_maker()() as session:
        return await session.get(CalendarSyncState, source_id)
