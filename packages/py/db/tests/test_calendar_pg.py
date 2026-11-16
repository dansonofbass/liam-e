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


def test_adapter_to_index_end_to_end(pg_db):
    async def run():
        from api.calendar import sync
        from api.calendar.adapters import Event, Occurrence, Snapshot
        from db.accessors import mail_job
        from db.accessors.calendar_occurrence import overlapping
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource

        class SyntheticAdapter:
            async def snapshot(self, source_id, start, end):
                return Snapshot([Event("master", recurrence={"rrule": "FREQ=DAILY"})],
                                [Occurrence("instance", "master", start_date=date(2026, 1, 1),
                                            end_date=date(2026, 1, 4))], True)

        source = CalendarSource(provider="synthetic_test", connection_ref="local", external_id="example", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        sync.register_adapter("synthetic_test", SyntheticAdapter())
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 5, tzinfo=UTC)
        assert await sync.enqueue(source.id, start, end)
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        await sync.run_sync({"source_id": source.id, "start": start.isoformat(), "end": end.isoformat()}, claim.id, claim.attempts)
        rows = await overlapping([source.id], start=datetime(2026, 1, 2, tzinfo=UTC), end=datetime(2026, 1, 3, tzinfo=UTC),
                                 start_date=date(2026, 1, 2), end_date=date(2026, 1, 3))
        assert len(rows) == 1 and rows[0].external_id == "instance"
        assert await mail_job.finish(claim.id, claim.attempts)

    asyncio.run(run())


def test_source_scope_and_delete(pg_db):
    async def run():
        from db.accessors import calendar_occurrence, calendar_source
        from db.engine import get_session_maker
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState

        source = CalendarSource(provider="synthetic", connection_ref="local", external_id="calendar", name="Example", timezone="UTC")
        event = CalendarEvent(source_id=source.id, external_id="event")
        occurrence = CalendarOccurrence(source_id=source.id, event_id=event.id, external_id="instance", start_date=date(2026, 1, 1), end_date=date(2026, 1, 3))
        async with get_session_maker()() as session:
            session.add_all([source, event, occurrence, CalendarSyncState(source_id=source.id)])
            await session.commit()
        assert (await calendar_occurrence.get_visible(occurrence.id)).id == occurrence.id
        await calendar_source.set_active(source.id, False)
        assert await calendar_occurrence.get_visible(occurrence.id) is None
        rows = await calendar_occurrence.page_visible(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC), start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), source_id=None, after=None, limit=10)
        assert rows == []
        assert await calendar_source.remove(source.id)
        async with get_session_maker()() as session:
            assert await session.get(CalendarEvent, event.id) is None
            assert await session.get(CalendarOccurrence, occurrence.id) is None
            assert await session.get(CalendarSyncState, source.id) is None
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
