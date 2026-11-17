"""Offline feed acquisition exercised against real transactional storage."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_setup_ttl_binding_cleanup_and_replacement(pg_db, monkeypatch, caplog):
    async def run():
        from api.calendar import feeds, ics
        from api.calendar.adapters import Snapshot
        from db.engine import get_session_maker
        from db.models.calendar_feed_validation import CalendarFeedValidation
        from db.models.calendar_feed_config import CalendarFeedConfig
        from env.mail import env
        monkeypatch.setattr(env, "mail_token_encryption_key", Fernet.generate_key().decode())
        async def snapshot(*args):
            return Snapshot([], [], True)
        monkeypatch.setattr(ics.ICSAdapter, "snapshot", snapshot)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        config = feeds.configuration(name="Example", url="https://calendar.example/test-only", timezone="UTC")
        preview = await feeds.validate(config, clock=lambda: now)
        assert "calendar.example" not in str(preview)
        assert preview["expires_at"] == now + timedelta(minutes=10)
        with pytest.raises(feeds.FeedError):
            await feeds.subscribe(preview["validation_id"], {**config, "timezone": "Europe/Berlin"}, now=now)
        attempts = await asyncio.gather(*(feeds.subscribe(preview["validation_id"], config, now=now) for _ in range(2)),
                                        return_exceptions=True)
        assert sum(isinstance(result, feeds.FeedError) for result in attempts) == 1
        source = next(result for result in attempts if not isinstance(result, Exception))
        with pytest.raises(feeds.FeedError):
            await feeds.subscribe(preview["validation_id"], config, now=now)
        expired = await feeds.validate(config, clock=lambda: now)
        with pytest.raises(feeds.FeedError):
            await feeds.subscribe(expired["validation_id"], config, now=now + timedelta(minutes=10))
        cancelled = await feeds.validate(config, clock=lambda: now)
        await feeds.discard(cancelled["validation_id"])
        replacement = {**config, "url": "https://calendar.example/test-only-new", "source_id": source.id,
                       "expected_revision": source.revision}
        preview = await feeds.validate(replacement, clock=lambda: now)
        updated = await feeds.subscribe(preview["validation_id"], replacement, now=now)
        assert updated.id == source.id and updated.revision == source.revision + 1
        async with get_session_maker()() as session:
            assert not (await session.execute(select(CalendarFeedValidation))).scalars().all()
            stored = await session.get(CalendarFeedConfig, source.id)
            assert "calendar.example" not in stored.encrypted_payload
            from api.calendar.feed_secrets import unseal
            assert unseal(stored.encrypted_payload)["url"] == replacement["url"]
        async def failure(*args):
            raise ValueError(config["url"])
        monkeypatch.setattr(ics.ICSAdapter, "snapshot", failure)
        with pytest.raises(feeds.FeedError) as error:
            await feeds.validate(config, clock=lambda: now)
        assert str(error.value) == "calendar_feed_unavailable" and error.value.__suppress_context__
        async with get_session_maker()() as session:
            assert not (await session.execute(select(CalendarFeedValidation))).scalars().all()
        assert "calendar.example" not in caplog.text
    asyncio.run(run())


def test_feed_snapshots_304_empty_failure_and_remove_during_fetch(pg_db, monkeypatch):
    async def run():
        from api.calendar import feeds, ics, ics_fetch, sync
        from api.calendar.feed_jobs import StoredICSAdapter
        from db.accessors import calendar_source, mail_job
        from db.engine import get_session_maker
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_sync_state import CalendarSyncState
        from env.mail import env
        monkeypatch.setattr(env, "mail_token_encryption_key", Fernet.generate_key().decode())
        day = datetime.now(UTC).date()
        start = datetime.combine(day, datetime.min.time(), UTC)
        window = [start, start + timedelta(days=2)]
        monkeypatch.setattr(ics, "default_window", lambda *args: tuple(window))
        response = {"status": 200, "body": b"", "etag": "test-only"}
        requested = []
        blocked, release = asyncio.Event(), asyncio.Event()
        block = False
        def body(title):
            return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:test-only\r\n"
                    f"DTSTART:{day.strftime('%Y%m%d')}T100000Z\r\nRRULE:FREQ=DAILY\r\nSUMMARY:{title}\r\n"
                    "END:VEVENT\r\nEND:VCALENDAR\r\n").encode()
        response["body"] = body("First")
        async def resolver(host):
            return ["93.184.216.34"]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield response["body"]
        async def handler(request):
            requested.append(dict(request.headers))
            if block:
                blocked.set()
                await release.wait()
            return httpx.Response(response["status"], headers={"content-type": "text/calendar", "etag": response["etag"]}, stream=Stream())
        async def fetch(url, **kwargs):
            return await ics_fetch.fetch(url, **kwargs, resolver=resolver, transport=httpx.MockTransport(handler))
        monkeypatch.setattr(ics, "fetch", fetch)
        config = feeds.configuration(name="Example", url="https://calendar.example/test-only", timezone="UTC")
        preview = await feeds.validate(config)
        source = await feeds.subscribe(preview["validation_id"], config)
        sync.register_adapter("ics", StoredICSAdapter())
        async def execute():
            claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
            if claim is None:
                await mail_job.enqueue("calendar_sync", {"source_id": source.id}, dedupe_key=f"calendar_sync:{source.id}")
                claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
            try:
                await sync.run_sync(json.loads(claim.payload_json), claim.id, claim.attempts)
            finally:
                await mail_job.finish(claim.id, claim.attempts)
        async def rows():
            async with get_session_maker()() as session:
                return list((await session.execute(select(CalendarOccurrence).where(CalendarOccurrence.source_id == source.id))).scalars())
        await execute()
        initial_ids = {row.id for row in await rows()}
        assert len(initial_ids) == 2
        response["body"], response["etag"] = body("Second"), "test-only-new"
        await execute()
        assert {row.title for row in await rows()} == {"Second"}
        assert {row.id for row in await rows()} == initial_ids
        response["status"] = 304
        window[:] = [start + timedelta(days=1), start + timedelta(days=3)]
        await execute()
        assert requested[-1]["if-none-match"] == "test-only-new"
        assert {row.start_at.date() for row in await rows()} == {day + timedelta(days=1), day + timedelta(days=2)}
        response["status"], response["body"] = 200, b"broken"
        with pytest.raises(LookupError):
            await execute()
        assert len(await rows()) == 2
        response["body"] = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
        await execute()
        assert await rows() == []
        response["body"] = body("Third")
        block = True
        task = asyncio.create_task(execute())
        await blocked.wait()
        await calendar_source.remove(source.id)
        release.set()
        from db.accessors.calendar_snapshot import LostClaim
        with pytest.raises(LostClaim):
            await task
        assert await rows() == []
        async with get_session_maker()() as session:
            assert await session.get(CalendarSyncState, source.id) is None
            from db.models.mail_job import MailJob
            assert not (await session.execute(select(MailJob).where(
                MailJob.dedupe_key == f"calendar_sync:{source.id}"))).scalars().all()
    asyncio.run(run())
