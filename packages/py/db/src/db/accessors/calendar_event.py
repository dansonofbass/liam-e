"""Calendar event lookups."""

from db.engine import get_session_maker
from db.models.calendar_event import CalendarEvent


async def get(event_id: str) -> CalendarEvent | None:
    async with get_session_maker()() as session:
        return await session.get(CalendarEvent, event_id)
