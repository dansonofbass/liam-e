"""Calendar occurrence overlap lookups."""

from datetime import date, datetime

from sqlalchemy import and_, or_, select

from db.engine import get_session_maker
from db.models.calendar_occurrence import CalendarOccurrence


async def overlapping(source_ids: list[str], *, start: datetime, end: datetime, start_date: date, end_date: date) -> list[CalendarOccurrence]:
    if not source_ids:
        return []
    stmt = select(CalendarOccurrence).where(
        CalendarOccurrence.source_id.in_(source_ids),
        or_(and_(CalendarOccurrence.start_at < end, CalendarOccurrence.end_at > start),
            and_(CalendarOccurrence.start_date < end_date, CalendarOccurrence.end_date > start_date)),
    ).order_by(CalendarOccurrence.id)
    async with get_session_maker()() as session:
        return list((await session.execute(stmt)).scalars())
