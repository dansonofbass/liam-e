"""Live Postgres contracts for calendar index constraints and overlap."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_unfiltered_window_uses_end_at_index(pg_db):
    async def run():
        from sqlalchemy import and_, or_, select, text
        from sqlalchemy.dialects import postgresql
        from db.accessors.calendar_occurrence import timed_overlap
        from db.engine import get_session_maker
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource

        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        stmt = (select(CalendarOccurrence).join(CalendarSource, CalendarOccurrence.source_id == CalendarSource.id)
                .where(CalendarSource.is_active.is_(True),
                       or_(timed_overlap(start, end),
                           and_(CalendarOccurrence.start_date < end.date(),
                                CalendarOccurrence.end_date > start.date()))))
        sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        async with get_session_maker()() as session:
            await session.execute(text("SET LOCAL enable_seqscan = off"))
            plan = "\n".join((await session.execute(text("EXPLAIN " + sql))).scalars())
            assert "ix_calendar_occurrence_end_at" in plan, plan
            assert "Seq Scan on calendar_occurrence" not in plan, plan
    asyncio.run(run())


def test_points_constraint_window_and_replacement(pg_db):
    async def run():
        from sqlalchemy import select
        from db.accessors import calendar_occurrence, mail_job
        from db.accessors.calendar_snapshot import replace_window
        from db.engine import get_session_maker
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource

        source = CalendarSource(provider="synthetic", connection_ref="local", external_id="points", name="Example", timezone="UTC")
        event = CalendarEvent(source_id=source.id, external_id="event")
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        def point(uid, instant):
            return CalendarOccurrence(source_id=source.id, event_id=event.id, external_id=uid,
                                      start_at=instant, end_at=instant, timezone="UTC")
        first, last = point("first", start), point("last", end)
        async with get_session_maker()() as session:
            session.add_all([source, event, first, last])
            await session.commit()
        async with get_session_maker()() as session:
            session.add(CalendarOccurrence(source_id=source.id, event_id=event.id, external_id="invalid",
                                           start_at=end, end_at=start, timezone="UTC"))
            with pytest.raises(IntegrityError):
                await session.commit()
        args = dict(start=start, end=end, start_date=start.date(), end_date=end.date())
        rows = await calendar_occurrence.page_visible(**args, source_ids=[source.id], after=None, limit=10)
        assert [row.external_id for row in rows] == ["first"]
        assert [row.external_id for row in await calendar_occurrence.overlapping([source.id], **args)] == ["first"]
        job = await mail_job.enqueue("calendar", {"source_id": source.id}, dedupe_key="points-calendar")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        await replace_window(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                             **args, events=[event], occurrences=[first])
        async with get_session_maker()() as session:
            stored = (await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == source.id))).scalars().all()
            assert [row.external_id for row in stored] == ["first"]
        await replace_window(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                             **args, events=[event], occurrences=[])
        async with get_session_maker()() as session:
            assert not (await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == source.id))).scalars().all()
    asyncio.run(run())


def test_point_migration_round_trip(pg_db):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from db.engine import dispose_engine, get_session_maker
    from db.models.calendar_occurrence import CalendarOccurrence
    from db.models.calendar_sync_state import CalendarSyncState

    async def seed():
        async with get_session_maker()() as session:
            instant = datetime(2026, 1, 1, tzinfo=UTC)
            session.add_all([CalendarSyncState(source_id="point-source", incomplete=False),
                             CalendarSyncState(source_id="other-source", incomplete=False),
                             CalendarOccurrence(source_id="point-source", event_id="event", external_id="point",
                                                start_at=instant, end_at=instant, timezone="UTC")])
            await session.commit()
    async def verify():
        from sqlalchemy import select
        async with get_session_maker()() as session:
            assert (await session.get(CalendarSyncState, "point-source")).incomplete
            assert not (await session.get(CalendarSyncState, "other-source")).incomplete
            assert not (await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == "point-source"))).scalars().all()
    project = Path(__file__).resolve().parents[1]
    config = Config(str(project / "alembic.ini"))
    config.set_main_option("script_location", str(project / "src/db/migrations"))
    asyncio.run(seed())
    asyncio.run(dispose_engine())
    command.downgrade(config, "9c420cfdeeb6")
    asyncio.run(verify())
    asyncio.run(dispose_engine())
    command.upgrade(config, "heads")
    asyncio.run(seed_after_upgrade())


async def seed_after_upgrade():
    from db.engine import get_session_maker
    from db.models.calendar_occurrence import CalendarOccurrence
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    async with get_session_maker()() as session:
        session.add(CalendarOccurrence(source_id="point-source", event_id="event", external_id="point",
                                       start_at=instant, end_at=instant, timezone="UTC"))
        await session.commit()


def test_large_snapshot_and_unknown_event(pg_db):
    async def run():
        from db.accessors import mail_job
        from db.accessors.calendar_snapshot import replace_window
        from db.engine import get_session_maker
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource

        source = CalendarSource(provider="synthetic", connection_ref="local", external_id="large", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        job = await mail_job.enqueue("calendar", {"source_id": source.id}, dedupe_key="large-calendar")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        event = CalendarEvent(source_id=source.id, external_id="event")
        rows = [CalendarOccurrence(source_id=source.id, event_id=event.id, external_id=str(i),
                                   start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)) for i in range(40000)]
        args = dict(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                    start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC),
                    start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), events=[event])
        bad = rows[0].model_copy(update={"event_id": "unknown"})
        with pytest.raises(ValueError, match="unknown event"):
            await replace_window(**args, occurrences=[bad])
        await replace_window(**args, occurrences=rows)
        await replace_window(**args, occurrences=rows)

    asyncio.run(run())


def test_snapshot_coverage_pruning_and_orphans(pg_db):
    async def run():
        from sqlalchemy import select
        from db.accessors import mail_job
        from db.accessors.calendar_snapshot import replace_window
        from db.engine import get_session_maker
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState

        source = CalendarSource(provider="synthetic", connection_ref="local", external_id="coverage", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        job = await mail_job.enqueue("calendar", {"source_id": source.id}, dedupe_key="coverage-calendar")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        event = CalendarEvent(source_id=source.id, external_id="event")
        timed = CalendarOccurrence(source_id=source.id, event_id=event.id, external_id="timed", timezone="UTC",
                                   start_at=datetime(2026, 1, 1, tzinfo=UTC), end_at=datetime(2026, 1, 3, tzinfo=UTC))
        allday = CalendarOccurrence(source_id=source.id, event_id=event.id, external_id="allday",
                                    start_date=date(2026, 1, 1), end_date=date(2026, 1, 3))
        async def replace(first, last, rows, events):
            await replace_window(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                                 start=datetime(2026, 1, first, tzinfo=UTC), end=datetime(2026, 1, last, tzinfo=UTC),
                                 start_date=date(2026, 1, first), end_date=date(2026, 1, last),
                                 events=events, occurrences=rows)
        await replace(2, 5, [timed, allday], [event])
        await replace(3, 4, [], [])
        async with get_session_maker()() as session:
            state = await session.get(CalendarSyncState, source.id)
            assert (state.coverage_start.day, state.coverage_end.day) == (2, 5)
            assert len((await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == source.id))).scalars().all()) == 2
        await replace(10, 12, [], [])
        async with get_session_maker()() as session:
            state = await session.get(CalendarSyncState, source.id)
            assert (state.coverage_start.day, state.coverage_end.day) == (10, 12)
            assert not (await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == source.id))).scalars().all()
            assert not (await session.execute(select(CalendarEvent).where(CalendarEvent.source_id == source.id))).scalars().all()

    asyncio.run(run())


def test_snapshot_retains_current_and_referenced_masters(pg_db):
    async def run():
        from sqlalchemy import select
        from db.accessors import mail_job
        from db.accessors.calendar_snapshot import replace_window
        from db.engine import get_session_maker
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource

        source = CalendarSource(provider="synthetic", connection_ref="local", external_id="masters", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        job = await mail_job.enqueue("calendar", {"source_id": source.id}, dedupe_key="masters-calendar")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        current = CalendarEvent(source_id=source.id, external_id="current", recurrence_json='{"rrule":"FREQ=YEARLY"}')
        referenced = CalendarEvent(source_id=source.id, external_id="referenced")
        orphan = CalendarEvent(source_id=source.id, external_id="orphan")
        row = CalendarOccurrence(source_id=source.id, event_id=referenced.id, external_id="outside",
                                 start_date=date(2026, 1, 2), end_date=date(2026, 1, 3))

        async def replace(first, last, events, rows):
            await replace_window(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                                 start=datetime(2026, 1, first, tzinfo=UTC), end=datetime(2026, 1, last, tzinfo=UTC),
                                 start_date=date(2026, 1, first), end_date=date(2026, 1, last),
                                 events=events, occurrences=rows)

        async def masters():
            async with get_session_maker()() as session:
                return {event.external_id: event for event in (await session.execute(
                    select(CalendarEvent).where(CalendarEvent.source_id == source.id))).scalars()}

        await replace(1, 5, [current, referenced, orphan], [row])
        assert set(await masters()) == {"current", "referenced", "orphan"}
        await replace(3, 4, [current], [])
        stored = await masters()
        assert set(stored) == {"current", "referenced"}
        assert stored["current"].recurrence_json == current.recurrence_json
        await replace(10, 12, [current], [])
        assert set(await masters()) == {"current"}

    asyncio.run(run())


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
        rows = await calendar_occurrence.page_visible(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC), start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), source_ids=None, after=None, limit=10)
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


def test_pages_are_chronological_and_filter_several_sources(pg_db):
    async def run():
        from db.accessors import calendar_occurrence
        from db.engine import get_session_maker
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource

        a, b, c = (CalendarSource(provider="synthetic", connection_ref="local", external_id=name, name=name,
                                  timezone="UTC") for name in ("a", "b", "c"))
        def timed(source, uid, hour):
            return CalendarOccurrence(source_id=source.id, event_id="event", external_id=uid, timezone="UTC",
                                      start_at=datetime(2026, 1, 2, hour, tzinfo=UTC),
                                      end_at=datetime(2026, 1, 2, hour + 1, tzinfo=UTC))
        rows = [timed(a, "late", 15), timed(b, "early", 8), timed(c, "hidden", 9),
                CalendarOccurrence(source_id=a.id, event_id="event", external_id="all-day",
                                   start_date=date(2026, 1, 2), end_date=date(2026, 1, 3)),
                timed(b, "noon", 12)]
        async with get_session_maker()() as session:
            session.add_all([a, b, c, *rows])
            await session.commit()
        window = dict(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 4, tzinfo=UTC),
                      start_date=date(2026, 1, 1), end_date=date(2026, 1, 4), source_ids=[a.id, b.id])
        seen, after = [], None
        while True:
            page = await calendar_occurrence.page_visible(**window, after=after, limit=2)
            seen += [row.external_id for row in page]
            if len(page) < 2:
                break
            after = (calendar_occurrence.sort_key(page[-1]), page[-1].id)
        # The all-day instance sorts at midnight UTC of its first day; source c is filtered out.
        assert seen == ["all-day", "early", "noon", "late"]

    asyncio.run(run())
