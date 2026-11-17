"""Calendar occurrence overlap lookups."""

from datetime import UTC, date, datetime, time

from sqlalchemy import DateTime, and_, cast, func, literal, or_, select, tuple_

from db.engine import get_session_maker
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_source import CalendarSource


async def get_visible(occurrence_id: str) -> CalendarOccurrence | None:
    stmt = (select(CalendarOccurrence).join(CalendarSource, CalendarOccurrence.source_id == CalendarSource.id)
            .where(CalendarOccurrence.id == occurrence_id, CalendarSource.is_active.is_(True)))
    async with get_session_maker()() as session:
        return (await session.execute(stmt)).scalar_one_or_none()


# Chronological order for both kinds of instance: a timed one by its UTC start, an all-day one by
# midnight UTC of its first day. `sort_key` computes the same value in Python for the cursor.
_SORT = func.coalesce(CalendarOccurrence.start_at,
                      func.timezone("UTC", cast(CalendarOccurrence.start_date, DateTime())))


def sort_key(row: CalendarOccurrence) -> datetime:
    if row.start_at is not None:
        return row.start_at.astimezone(UTC)
    assert row.start_date is not None
    return datetime.combine(row.start_date, time.min, tzinfo=UTC)


async def page_visible(*, start: datetime, end: datetime, start_date: date, end_date: date,
                       source_ids: list[str] | None, after: tuple[datetime, str] | None,
                       limit: int) -> list[CalendarOccurrence]:
    """One page of instances from active sources that overlap the window, in chronological order.

    `after` is the (sort key, id) of the last row of the previous page; the pair is unique, so
    paging neither repeats nor skips a row that stays in the index between two pages.
    """
    stmt = (select(CalendarOccurrence).join(CalendarSource, CalendarOccurrence.source_id == CalendarSource.id)
            .where(CalendarSource.is_active.is_(True),
                   or_(and_(CalendarOccurrence.start_at < end, CalendarOccurrence.end_at > start),
                       and_(CalendarOccurrence.start_date < end_date, CalendarOccurrence.end_date > start_date))))
    if source_ids:
        stmt = stmt.where(CalendarOccurrence.source_id.in_(source_ids))
    if after:
        stmt = stmt.where(tuple_(_SORT, CalendarOccurrence.id)
                          > tuple_(literal(after[0], DateTime(timezone=True)), literal(after[1])))
    stmt = stmt.order_by(_SORT, CalendarOccurrence.id).limit(limit)
    async with get_session_maker()() as session:
        return list((await session.execute(stmt)).scalars())


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
