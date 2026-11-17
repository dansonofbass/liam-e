"""Persistent polling and manual cooldown with an injected clock."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_persistent_interval_pause_manual_throttle_and_bounded_failures(pg_db):
    async def run():
        from db.accessors import calendar_feed_sync, calendar_source, mail_job
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState
        source = CalendarSource(provider="ics", connection_ref="private", external_id="test-only", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        async def enqueue(at=now, manual=False):
            return await calendar_feed_sync.enqueue(source.id, now=at, interval=30, manual=manual)
        async def finish(at):
            claim = await mail_job.claim_next(at, stale_after=timedelta(minutes=5))
            assert claim is not None
            await mail_job.finish(claim.id, claim.attempts)
        assert await enqueue()
        assert not await enqueue()
        await finish(now)
        assert not await enqueue(now + timedelta(minutes=29))
        assert not await enqueue(now + timedelta(seconds=59), True)
        assert await enqueue(now + timedelta(minutes=1), True)
        await finish(now + timedelta(minutes=1))
        await calendar_source.set_active(source.id, False)
        assert not await enqueue(now + timedelta(hours=1))
        assert not await enqueue(now + timedelta(hours=1), True)
        resumed = await calendar_source.set_active(source.id, True)
        for count in range(3):
            at = now + timedelta(hours=2, minutes=count)
            await calendar_feed_sync.failure(source.id, revision=resumed.revision, now=at,
                                             code="feed_unavailable", delay_seconds=30)
            assert not await enqueue(at + timedelta(seconds=29))
            if count < 2:
                assert await enqueue(at + timedelta(seconds=30))
                await finish(at + timedelta(seconds=30))
        last_failure = now + timedelta(hours=2, minutes=2)
        assert not await enqueue(last_failure + timedelta(minutes=29, seconds=59))
        assert await enqueue(last_failure + timedelta(minutes=30))
        await finish(last_failure + timedelta(minutes=30))
        # Further failures stay on the regular interval, not a new short retry loop.
        await calendar_feed_sync.failure(source.id, revision=resumed.revision,
                                         now=last_failure + timedelta(minutes=30),
                                         code="feed_unavailable", delay_seconds=120)
        assert not await enqueue(last_failure + timedelta(minutes=32))
        assert await enqueue(last_failure + timedelta(minutes=60))
        await finish(last_failure + timedelta(minutes=60))
        async with get_session_maker()() as session:
            state = await session.get(CalendarSyncState, source.id)
            assert state.failure_count == 3
        assert await enqueue(now + timedelta(days=1), True)
        await finish(now + timedelta(days=1))
        await calendar_feed_sync.failure(source.id, revision=resumed.revision, now=now + timedelta(days=1),
                                         code="address_check", delay_seconds=None)
        assert not await enqueue(now + timedelta(days=2))
        async with get_session_maker()() as session:
            state = await session.get(CalendarSyncState, source.id)
            assert state.last_error == "address_check" and state.failure_count == 3
    asyncio.run(run())
