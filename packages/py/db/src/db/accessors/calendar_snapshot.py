"""Atomic, claim-fenced replacement of one calendar window."""

import json
from datetime import date, datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert

from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.calendar_event import CalendarEvent
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState
from db.models.mail_job import MailJob


class LostClaim(Exception):
    """The worker no longer owns the job or the source is inactive."""


async def replace_window(*, source_id: str, job_id: str, attempt: int,
                         start: datetime, end: datetime, start_date: date, end_date: date,
                         events: list[CalendarEvent], occurrences: list[CalendarOccurrence]) -> None:
    """Replace a fully processed window; inputs are prepared before the transaction.

    Callers must validate adapter completeness and interval normalization before calling.
    """
    if start.tzinfo is None or end.tzinfo is None or start >= end or start_date >= end_date:
        raise ValueError("invalid window")
    if any(event.source_id != source_id or len(event.recurrence_json.encode("utf-8")) > 65536 for event in events):
        raise ValueError("invalid event")
    if any(not isinstance(json.loads(event.recurrence_json), dict) for event in events):
        raise ValueError("invalid recurrence")
    if any(row.source_id != source_id for row in occurrences):
        raise ValueError("invalid occurrence")
    if len({row.external_id for row in events}) != len(events) or len({row.external_id for row in occurrences}) != len(occurrences):
        raise ValueError("duplicate identity")
    if any(row.event_id not in {event.id for event in events} for row in occurrences):
        raise ValueError("unknown event")
    async with get_session_maker()() as session:
        job = (await session.execute(select(MailJob).where(MailJob.id == job_id).with_for_update())).scalar_one_or_none()
        if (job is None or job.status != "running" or job.attempts != attempt
                or json.loads(job.payload_json).get("source_id") != source_id):
            raise LostClaim()
        source = (await session.execute(select(CalendarSource).where(CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if source is None or not source.is_active:
            raise LostClaim()
        event_ids = {}
        for event in events:
            values = event.model_dump()
            stmt = insert(CalendarEvent).values(**values).on_conflict_do_update(
                constraint="uq_calendar_event_external", set_={"title": event.title, "recurrence_json": event.recurrence_json},
            ).returning(CalendarEvent.id)
            event_ids[event.id] = (await session.execute(stmt)).scalar_one()
        overlap = or_(and_(CalendarOccurrence.start_at < end, CalendarOccurrence.end_at > start),
                      and_(CalendarOccurrence.start_date < end_date, CalendarOccurrence.end_date > start_date))
        delete_stmt = delete(CalendarOccurrence).where(CalendarOccurrence.source_id == source_id, overlap)
        if occurrences:
            delete_stmt = delete_stmt.where(CalendarOccurrence.external_id.not_in([row.external_id for row in occurrences]))
        await session.execute(delete_stmt)
        for row in occurrences:
            values = row.model_dump()
            values["event_id"] = event_ids[row.event_id]
            changes = {key: value for key, value in values.items() if key not in ("id", "source_id", "external_id")}
            await session.execute(insert(CalendarOccurrence).values(**values).on_conflict_do_update(
                constraint="uq_calendar_occurrence_external", set_=changes,
            ))
        state = CalendarSyncState(source_id=source_id, coverage_start=start, coverage_end=end,
                                  last_success_at=utcnow(), incomplete=False)
        values = state.model_dump()
        await session.execute(insert(CalendarSyncState).values(**values).on_conflict_do_update(
            index_elements=[CalendarSyncState.source_id], set_={k: v for k, v in values.items() if k != "source_id"},
        ))
        await session.commit()
