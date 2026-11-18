"""Offline Google snapshots against real claim- and revision-fenced Postgres storage."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")
FIXTURES = Path(__file__).resolve().parents[4] / "apps/api/tests/fixtures/google_calendar"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_generations_failure_identity_and_schedule_reset(pg_db, monkeypatch):
    async def run():
        from api.calendar import google, ics, sync
        from db.accessors import calendar_source, mail_job
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_sync_state import CalendarSyncState

        start, end = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)
        now = datetime.now(UTC)
        monkeypatch.setattr(ics, "default_window", lambda: (start, end))
        mode = "initial"
        primary = "work@example.org"

        async def call(tool, args):
            if "calendarId" not in args:
                return {"summary": primary, "events": []}
            if mode == "error":
                raise google.GoogleError()
            if mode == "moved":
                return fixture("events_moved")
            return fixture("events_2" if args.get("pageToken") else "events_1")

        ref = await google.identity(call=call, now=now)
        sources = [CalendarSource(provider="google", connection_ref=ref, external_id=name,
                                  name="Example", timezone="Europe/Berlin") for name in ("work@example.org", "garden@example.org")]
        async with get_session_maker()() as session:
            session.add_all(sources)
            await session.commit()
        monkeypatch.setitem(sync._adapters, "google", google.GoogleConnectorAdapter(call=call))

        async def execute(source):
            await mail_job.enqueue("calendar_sync", {"source_id": source.id}, dedupe_key=f"calendar_sync:{source.id}")
            claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
            try:
                await sync.run_sync(json.loads(claim.payload_json), claim.id, claim.attempts)
            finally:
                await mail_job.finish(claim.id, claim.attempts)

        async def rows(source):
            async with get_session_maker()() as session:
                return list((await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == source.id))).scalars())

        for source in sources:
            await execute(source)
        initial = {r.external_id: r for r in await rows(sources[0])}
        other = {r.id for r in await rows(sources[1])}
        assert len(initial) == 4
        async with get_session_maker()() as session:
            state = await session.get(CalendarSyncState, sources[0].id)
            revision = state.data_revision
            state.failure_count, state.last_error = 3, "provider_unavailable"
            state.next_attempt_at = now + timedelta(hours=1)
            # Google success must reset scheduling without encrypted HTTP validators.
            assert state.encrypted_validators is None
            session.add(state)
            await session.commit()
        mode = "moved"
        await execute(sources[0])
        moved = (await rows(sources[0]))[0]
        assert moved.id == initial[moved.external_id].id
        assert moved.start_at != initial[moved.external_id].start_at
        assert {r.id for r in await rows(sources[1])} == other
        async with get_session_maker()() as session:
            state = await session.get(CalendarSyncState, sources[0].id)
            assert state.data_revision == revision + 1
            assert state.last_error is None and state.failure_count == 0 and state.next_attempt_at is None
            assert state.last_checked_at == state.last_validated_at == state.last_success_at
            success = state.last_success_at
        for change in ("error", "identity"):
            mode = "error" if change == "error" else "moved"
            if change == "identity":
                primary = "other@example.org"
            with pytest.raises(google.GoogleError):
                await execute(sources[0])
            assert [r.id for r in await rows(sources[0])] == [moved.id]
            async with get_session_maker()() as session:
                state = await session.get(CalendarSyncState, sources[0].id)
                assert state.last_success_at == success and state.data_revision == revision + 1
                assert state.last_error == ("provider_unavailable" if change == "error" else "reconnect_required")
        # Pause/resume advances the revision; old provider work cannot activate.
        from db.accessors.calendar_snapshot import LostClaim, replace_window
        await calendar_source.set_active(sources[0].id, False)
        await calendar_source.set_active(sources[0].id, True)
        job = await mail_job.enqueue("calendar_sync", {"source_id": sources[0].id}, dedupe_key="stale-google")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        with pytest.raises(LostClaim):
            await replace_window(source_id=sources[0].id, job_id=job.id, attempt=claim.attempts,
                                 start=start, end=end, start_date=start.date(), end_date=end.date(),
                                 events=[], occurrences=[], expected_revision=sources[0].revision,
                                 replace_all=True, reset_schedule=True)
        assert [r.id for r in await rows(sources[0])] == [moved.id]
    asyncio.run(run())


@pytest.mark.parametrize("code", ["reconnect_required", "calendar_unavailable"])
def test_google_gate_stops_and_manual_cooldown_lifts_stop(pg_db, code):
    async def run():
        from db.accessors import calendar_feed_sync
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState
        now = datetime.now(UTC)
        source = CalendarSource(provider="google", connection_ref="google_calendar#test-only", external_id="work@example.org", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            session.add(CalendarSyncState(source_id=source.id, last_checked_at=now, last_error=code, failure_count=3))
            await session.commit()
        assert not await calendar_feed_sync.enqueue(source.id, now=now + timedelta(minutes=10), interval=5, manual=False)
        assert not await calendar_feed_sync.enqueue(source.id, now=now + timedelta(seconds=30), interval=5, manual=True)
        assert await calendar_feed_sync.enqueue(source.id, now=now + timedelta(minutes=1), interval=5, manual=False)
    asyncio.run(run())
