"""HTTP failure classes, cancellation and retry ceilings without network access."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


@pytest.mark.parametrize("code", ["auth_required", "rate_limited", "provider_error", "fetch_error"])
def test_http_errors_preserve_generation_and_have_finite_retry_state(pg_db, monkeypatch, caplog, code):
    async def run():
        from api.calendar import feed_jobs, feed_secrets, ics
        from api.calendar.ics_fetch import FetchResult
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_feed_config import CalendarFeedConfig
        from db.models.calendar_sync_state import CalendarSyncState
        from env.mail import env
        monkeypatch.setattr(env, "mail_token_encryption_key", Fernet.generate_key().decode())
        source = CalendarSource(provider="ics", connection_ref="private", external_id="test-only", name="Example", timezone="UTC")
        now = datetime(2026, 1, 1, tzinfo=UTC)
        async with get_session_maker()() as session:
            session.add_all([source, CalendarFeedConfig(source_id=source.id, encrypted_payload=feed_secrets.seal({"url": "https://calendar.example/test-only"})),
                             CalendarSyncState(source_id=source.id, coverage_start=now, coverage_end=now + timedelta(days=2),
                                               last_success_at=now, incomplete=False, data_revision=7)])
            await session.commit()
        async def fetch(*args, **kwargs):
            return FetchResult(code)
        monkeypatch.setattr(ics, "fetch", fetch)
        current = now + timedelta(hours=1)
        adapter = feed_jobs.StoredICSAdapter(clock=lambda: current, jitter=lambda low, high: (low + high) / 2)
        for attempt in range(1, 4):
            with pytest.raises(LookupError, match="^calendar_feed_unavailable$"):
                await adapter.snapshot(source.id, now, now + timedelta(days=2))
            async with get_session_maker()() as session:
                state = await session.get(CalendarSyncState, source.id)
                assert state.data_revision == 7 and state.last_success_at == now
                assert state.coverage_end == now + timedelta(days=2) and not state.incomplete
                assert state.last_checked_at == current
                if code == "auth_required":
                    assert state.last_error == "address_check" and state.next_attempt_at is None
                    break
                assert state.last_error == "feed_unavailable"
                assert state.failure_count == attempt
                assert state.next_attempt_at == (current + timedelta(seconds=45 * 2 ** (attempt - 1)) if attempt < 3 else None)
            current += timedelta(minutes=5)
        assert "calendar.example" not in caplog.text
    asyncio.run(run())


@pytest.mark.parametrize("after_commit", [False, True])
def test_cancelled_validation_leaves_no_private_proof(pg_db, monkeypatch, after_commit):
    async def run():
        from api.calendar import feeds, ics
        from db.engine import get_session_maker
        from db.models.calendar_feed_validation import CalendarFeedValidation
        from env.mail import env
        monkeypatch.setattr(env, "mail_token_encryption_key", Fernet.generate_key().decode())
        started = asyncio.Event()
        async def pending(*args):
            started.set()
            await asyncio.Future()
        if after_commit:
            from sqlalchemy.ext.asyncio import AsyncSession
            from api.calendar.adapters import Snapshot
            original_commit = AsyncSession.commit
            async def commit(session):
                proof = any(isinstance(row, CalendarFeedValidation) for row in session.identity_map.values())
                await original_commit(session)
                if proof:
                    raise asyncio.CancelledError
            # add() flushes the proof before commit, so it is in the identity map.
            # Keep a strong reference through the add seam to model cancellation
            # immediately after the database has acknowledged the write.
            original_add = feeds.calendar_feed_validation.add
            retained = []
            async def add(session, row):
                retained.append(row)
                await original_add(session, row)
            async def complete(*args):
                return Snapshot([], [], True)
            monkeypatch.setattr(feeds.calendar_feed_validation, "add", add)
            monkeypatch.setattr(AsyncSession, "commit", commit)
            monkeypatch.setattr(ics.ICSAdapter, "snapshot", complete)
        else:
            monkeypatch.setattr(ics.ICSAdapter, "snapshot", pending)
        config = feeds.configuration(name="Example", url="https://calendar.example/test-only", timezone="UTC")
        task = asyncio.create_task(feeds.validate(config))
        if not after_commit:
            await started.wait()
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with get_session_maker()() as session:
            assert not (await session.execute(select(CalendarFeedValidation))).scalars().all()
    asyncio.run(run())
