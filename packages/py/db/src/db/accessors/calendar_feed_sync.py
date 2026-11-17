"""Private ICS snapshot inputs and persistent scheduling, fenced by source revision."""

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.engine import get_session_maker
from db.accessors._calendar_lock import lock_source
from db.models.calendar_event import CalendarEvent
from db.models.calendar_feed_config import CalendarFeedConfig
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState
from db.models.mail_job import MailJob


async def inputs(source_id: str):
    async with get_session_maker()() as session:
        source = (await session.execute(select(CalendarSource).where(
            CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if source is None or not source.is_active:
            raise LookupError("source_unavailable")
        config = await session.get(CalendarFeedConfig, source_id)
        state = await session.get(CalendarSyncState, source_id)
        events = list((await session.execute(select(CalendarEvent).where(CalendarEvent.source_id == source_id))).scalars())
        return source, config, state, events


async def enqueue(source_id: str, *, now: datetime, interval: int, manual: bool) -> bool:
    async with get_session_maker()() as session:
        await lock_source(session, source_id)
        source = (await session.execute(select(CalendarSource).where(
            CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if source is None or source.provider != "ics" or not source.is_active:
            return False
        state = await session.get(CalendarSyncState, source_id)
        if state:
            if manual:
                if state.last_checked_at and now < state.last_checked_at + timedelta(minutes=1):
                    return False
            else:
                if state.failure_count >= 3 or state.last_error == "address_check":
                    return False
                due = state.next_attempt_at or (state.last_checked_at + timedelta(minutes=interval) if state.last_checked_at else now)
                if now < due:
                    return False
        job = MailJob(kind="calendar_sync", payload_json=json.dumps({"source_id": source_id}),
                      dedupe_key=f"calendar_sync:{source_id}", run_after=now)
        inserted = (await session.execute(insert(MailJob).values(**job.model_dump()).on_conflict_do_nothing()
                                          .returning(MailJob.id))).scalar_one_or_none()
        if inserted is None:
            return False
        state = state or CalendarSyncState(source_id=source_id)
        state.last_checked_at = now
        state.next_attempt_at = now + timedelta(minutes=interval)
        if manual:
            state.failure_count = 0
            state.last_error = None
        session.add(state)
        await session.commit()
        return True


async def failure(source_id: str, *, revision: int, now: datetime, code: str, delay_seconds: float | None):
    async with get_session_maker()() as session:
        source = (await session.execute(select(CalendarSource).where(
            CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if source is None or not source.is_active or source.revision != revision:
            return
        state = await session.get(CalendarSyncState, source_id) or CalendarSyncState(source_id=source_id)
        state.last_checked_at = now
        state.last_error = code
        state.failure_count += 1
        state.next_attempt_at = now + timedelta(seconds=delay_seconds) if delay_seconds is not None and state.failure_count < 3 else None
        if delay_seconds is None:
            state.failure_count = 3
        session.add(state)
        await session.commit()
