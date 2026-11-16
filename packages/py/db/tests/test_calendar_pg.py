"""Live Postgres contracts for calendar index constraints and overlap."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_occurrence_identity_and_overlap(pg_db):
    async def run():
        from db.accessors.calendar_occurrence import overlapping
        from db.engine import get_session_maker
        from db.models.calendar_occurrence import CalendarOccurrence

        async with get_session_maker()() as session:
            session.add(CalendarOccurrence(source_id="a", event_id="e", external_id="one", start_date=date(2026, 1, 1), end_date=date(2026, 1, 4)))
            session.add(CalendarOccurrence(source_id="b", event_id="e", external_id="one", start_date=date(2026, 1, 1), end_date=date(2026, 1, 4)))
            await session.commit()
        rows = await overlapping(["a"], start=datetime(2026, 1, 2, tzinfo=UTC), end=datetime(2026, 1, 3, tzinfo=UTC), start_date=date(2026, 1, 2), end_date=date(2026, 1, 3))
        assert len(rows) == 1 and rows[0].source_id == "a"
        async with get_session_maker()() as session:
            session.add(CalendarOccurrence(source_id="a", event_id="e", external_id="one", start_date=date(2026, 1, 2), end_date=date(2026, 1, 3)))
            with pytest.raises(IntegrityError):
                await session.commit()

    asyncio.run(run())


def test_snapshot_rollback_and_parallel_replacement(pg_db):
    async def run():
        from db.accessors import mail_job
        from db.accessors.calendar_occurrence import overlapping
        from db.accessors.calendar_snapshot import LostClaim, replace_window
        from db.engine import get_session_maker
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource

        source = CalendarSource(provider="synthetic", connection_ref="local", external_id="calendar", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        job = await mail_job.enqueue("calendar", {"source_id": source.id}, dedupe_key="calendar-test")
        now = datetime.now(UTC) + timedelta(seconds=1)
        first = await mail_job.claim_next(now, stale_after=timedelta(seconds=1))
        second = await mail_job.claim_next(now + timedelta(seconds=2), stale_after=timedelta(seconds=1))
        event = CalendarEvent(source_id=source.id, external_id="event")
        def row(uid, end_day=3):
            return CalendarOccurrence(source_id=source.id, event_id=event.id, external_id=uid,
                                      start_date=date(2026, 1, 2), end_date=date(2026, 1, end_day))
        common = dict(source_id=source.id, job_id=job.id, start=datetime(2026, 1, 1, tzinfo=UTC),
                      end=datetime(2026, 1, 5, tzinfo=UTC), start_date=date(2026, 1, 1),
                      end_date=date(2026, 1, 5), events=[event])
        with pytest.raises(LostClaim):
            await replace_window(**common, attempt=first.attempts, occurrences=[row("old")])
        await replace_window(**common, attempt=second.attempts, occurrences=[row("initial")])
        with pytest.raises(IntegrityError):
            await replace_window(**common, attempt=second.attempts, occurrences=[row("invalid", 1)])
        async def get_ids():
            return {r.external_id for r in await overlapping([source.id], start=common["start"], end=common["end"],
                                                              start_date=common["start_date"], end_date=common["end_date"])}
        assert await get_ids() == {"initial"}
        await asyncio.gather(*(replace_window(**common, attempt=second.attempts, occurrences=[row(uid)]) for uid in ("one", "two")))
        assert await get_ids() in ({"one"}, {"two"})
        await replace_window(**common, attempt=second.attempts, occurrences=[])
        assert await get_ids() == set()

    asyncio.run(run())
