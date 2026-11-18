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
        # The owner can still trigger a manual check after an address error.
        assert await enqueue(now + timedelta(days=2), True)
    asyncio.run(run())


def test_resume_during_the_cooldown_restores_polling_after_an_address_error(pg_db):
    async def run():
        from db.accessors import calendar_feed_sync, calendar_source, mail_job
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        source = CalendarSource(provider="ics", connection_ref="private", external_id="test-only", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        async def enqueue(at, manual=False):
            return await calendar_feed_sync.enqueue(source.id, now=at, interval=30, manual=manual)
        assert await enqueue(now)
        claim = await mail_job.claim_next(now, stale_after=timedelta(minutes=5))
        await mail_job.finish(claim.id, claim.attempts)
        revision = (await calendar_source.get(source.id)).revision
        failed = now + timedelta(minutes=5)
        await calendar_feed_sync.failure(source.id, revision=revision, now=failed, code="address_check", delay_seconds=None)
        # Pause and resume within the minute after the failure, as the source controls do.
        await calendar_source.set_active(source.id, False)
        await calendar_source.set_active(source.id, True)
        assert not await enqueue(failed + timedelta(seconds=20), manual=True)
        assert not await enqueue(failed + timedelta(seconds=59))
        # The resume lifted the address stop, so the scheduler fetches once the cooldown ends.
        assert await enqueue(failed + timedelta(minutes=1))
    asyncio.run(run())
