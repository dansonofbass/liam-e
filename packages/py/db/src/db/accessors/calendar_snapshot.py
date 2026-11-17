"""Atomic, claim-fenced replacement of one calendar window."""

import json
from datetime import date, datetime

from sqlalchemy import String, and_, bindparam, delete, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, insert

from db.accessors.calendar_occurrence import timed_overlap
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
    input_event_ids = {event.id for event in events}
    if any(row.event_id not in input_event_ids for row in occurrences):
        raise ValueError("unknown event")
    async with get_session_maker()() as session:
        job = (await session.execute(select(MailJob).where(MailJob.id == job_id).with_for_update())).scalar_one_or_none()
        if (job is None or job.status != "running" or job.attempts != attempt
                or json.loads(job.payload_json).get("source_id") != source_id):
            raise LostClaim()
        source = (await session.execute(select(CalendarSource).where(CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if source is None or not source.is_active:
            raise LostClaim()
        state = await session.get(CalendarSyncState, source_id)
        coverage_start, coverage_end = start, end
        if (state and not state.incomplete and state.coverage_start is not None and state.coverage_end is not None
                and start <= state.coverage_end and end >= state.coverage_start):
            coverage_start = min(start, state.coverage_start)
            coverage_end = max(end, state.coverage_end)
        event_ids = {}
        for offset in range(0, len(events), 500):
            batch = events[offset:offset + 500]
            stmt = insert(CalendarEvent).values([event.model_dump() for event in batch])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_calendar_event_external",
                set_={"title": stmt.excluded.title, "recurrence_json": stmt.excluded.recurrence_json},
            ).returning(CalendarEvent.id, CalendarEvent.external_id)
            actual = {external: identifier for identifier, external in (await session.execute(stmt)).all()}
            event_ids.update({event.id: actual[event.external_id] for event in batch})
        overlap = or_(timed_overlap(start, end),
                      and_(CalendarOccurrence.start_date < end_date, CalendarOccurrence.end_date > start_date))
        delete_stmt = delete(CalendarOccurrence).where(CalendarOccurrence.source_id == source_id, overlap)
        if occurrences:
            retained = func.unnest(bindparam("retained_ids", [row.external_id for row in occurrences],
                                            type_=ARRAY(String))).table_valued("id").render_derived()
            delete_stmt = delete_stmt.where(~select(1).select_from(retained).where(
                retained.c.id == CalendarOccurrence.external_id).exists())
        await session.execute(delete_stmt)
        for offset in range(0, len(occurrences), 500):
            batch = []
            for row in occurrences[offset:offset + 500]:
                values = row.model_dump()
                values["event_id"] = event_ids[row.event_id]
                batch.append(values)
            stmt = insert(CalendarOccurrence).values(batch)
            changes = {key: getattr(stmt.excluded, key) for key in batch[0] if key not in ("id", "source_id", "external_id")}
            await session.execute(stmt.on_conflict_do_update(constraint="uq_calendar_occurrence_external", set_=changes))
        covered = or_(timed_overlap(coverage_start, coverage_end),
                      and_(CalendarOccurrence.start_date < coverage_end.date(), CalendarOccurrence.end_date > coverage_start.date()))
        await session.execute(delete(CalendarOccurrence).where(CalendarOccurrence.source_id == source_id,
                                                               ~func.coalesce(covered, False)))
        referenced = select(CalendarOccurrence.id).where(CalendarOccurrence.event_id == CalendarEvent.id,
                                                        CalendarOccurrence.source_id == source_id).exists()
        delete_events = delete(CalendarEvent).where(CalendarEvent.source_id == source_id, ~referenced)
        if events:
            retained_events = func.unnest(bindparam("retained_event_ids", [event.external_id for event in events],
                                                   type_=ARRAY(String))).table_valued("id").render_derived()
            delete_events = delete_events.where(~select(1).select_from(retained_events).where(
                retained_events.c.id == CalendarEvent.external_id).exists())
        await session.execute(delete_events)
        state = CalendarSyncState(source_id=source_id, coverage_start=coverage_start, coverage_end=coverage_end,
                                  last_success_at=utcnow(), incomplete=False)
        values = state.model_dump()
        await session.execute(insert(CalendarSyncState).values(**values).on_conflict_do_update(
            index_elements=[CalendarSyncState.source_id], set_={k: v for k, v in values.items() if k != "source_id"},
        ))
        await session.commit()
