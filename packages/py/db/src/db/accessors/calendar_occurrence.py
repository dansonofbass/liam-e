"""Calendar occurrence overlap lookups."""

from datetime import date, datetime

from sqlalchemy import and_, or_, select

from db.engine import get_session_maker
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_source import CalendarSource


async def get_visible(occurrence_id: str) -> CalendarOccurrence | None:
    stmt = (select(CalendarOccurrence).join(CalendarSource, CalendarOccurrence.source_id == CalendarSource.id)
            .where(CalendarOccurrence.id == occurrence_id, CalendarSource.is_active.is_(True)))
    async with get_session_maker()() as session:
        return (await session.execute(stmt)).scalar_one_or_none()


async def page_visible(*, start: datetime, end: datetime, start_date: date, end_date: date,
                       source_id: str | None, after: str | None, limit: int) -> list[CalendarOccurrence]:
    stmt = (select(CalendarOccurrence).join(CalendarSource, CalendarOccurrence.source_id == CalendarSource.id)
            .where(CalendarSource.is_active.is_(True),
                   or_(and_(CalendarOccurrence.start_at < end, CalendarOccurrence.end_at > start),
                       and_(CalendarOccurrence.start_date < end_date, CalendarOccurrence.end_date > start_date))))
    if source_id:
        stmt = stmt.where(CalendarOccurrence.source_id == source_id)
    if after:
        stmt = stmt.where(CalendarOccurrence.id > after)
    async with get_session_maker()() as session:
        return list((await session.execute(stmt.order_by(CalendarOccurrence.id).limit(limit))).scalars())


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
