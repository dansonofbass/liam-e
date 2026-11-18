"""Apply a confirmed provider result without pretending to extend snapshot coverage."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from db.accessors._calendar_lock import lock_source
from db.engine import get_session_maker
from db.models.calendar_event import CalendarEvent
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState


async def apply(*, source_id: str, upsert: tuple[CalendarEvent, CalendarOccurrence] | None,
                delete_external_id: str | None, expected_revision: int | None = None) -> bool:
    async with get_session_maker()() as session:
        await lock_source(session, source_id)
        source = (await session.execute(select(CalendarSource).where(CalendarSource.id == source_id)
                                       .with_for_update())).scalar_one_or_none()
        if source is None or not source.is_active or (expected_revision is not None and source.revision != expected_revision):
            return False
        state = await session.get(CalendarSyncState, source_id)
        if upsert is not None:
            event, row = upsert
            if event.source_id != source_id or row.source_id != source_id or row.event_id != event.id:
                raise ValueError("calendar_unavailable")
            covered = False
            if state and state.coverage_start and state.coverage_end:
                if row.start_date is not None:
                    covered = row.start_date < state.coverage_end.date() and row.end_date > state.coverage_start.date()
                else:
                    covered = (row.start_at < state.coverage_end and row.end_at >= state.coverage_start
                               and (row.end_at > state.coverage_start or row.start_at == row.end_at))
            if covered:
                stmt = insert(CalendarEvent).values(**event.model_dump())
                actual_id = (await session.execute(stmt.on_conflict_do_update(
                    constraint="uq_calendar_event_external", set_={"title": stmt.excluded.title,
                        "recurrence_json": stmt.excluded.recurrence_json}).returning(CalendarEvent.id))).scalar_one()
                values = row.model_dump()
                values["event_id"] = actual_id
                stmt = insert(CalendarOccurrence).values(**values)
                await session.execute(stmt.on_conflict_do_update(constraint="uq_calendar_occurrence_external",
                    set_={k: getattr(stmt.excluded, k) for k in values if k not in {"id", "source_id", "external_id"}}))
            else:
                delete_external_id = row.external_id
        if delete_external_id is not None:
            event_ids = list((await session.execute(delete(CalendarOccurrence).where(CalendarOccurrence.source_id == source_id,
                CalendarOccurrence.external_id == delete_external_id).returning(CalendarOccurrence.event_id))).scalars())
            referenced = select(CalendarOccurrence.id).where(CalendarOccurrence.event_id == CalendarEvent.id).exists()
            if event_ids:
                await session.execute(delete(CalendarEvent).where(CalendarEvent.source_id == source_id,
                    CalendarEvent.id.in_(event_ids), ~referenced))
        if state is None:
            state = CalendarSyncState(source_id=source_id)
            session.add(state)
        state.data_revision += 1
        await session.commit()
        return True


async def event_metadata(event_id: str) -> str:
    async with get_session_maker()() as session:
        event = await session.get(CalendarEvent, event_id)
        return event.recurrence_json if event else "{}"


async def find(source_id: str, external_id: str) -> CalendarOccurrence | None:
    async with get_session_maker()() as session:
        return (await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == source_id,
            CalendarOccurrence.external_id == external_id))).scalar_one_or_none()
