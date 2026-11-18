"""Postgres contracts for calendar writing; synthetic data only."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_replace_window_sets_capabilities_in_the_same_transaction(pg_db):
    async def run():
        from db.accessors import calendar_source, mail_job
        from db.accessors.calendar_snapshot import LostClaim, replace_window
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource

        source = CalendarSource(provider="google", connection_ref="synthetic", external_id="synthetic", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        job = await mail_job.enqueue("calendar", {"source_id": source.id}, dedupe_key="capabilities")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        args = dict(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                    start=start, end=end, start_date=start.date(), end_date=end.date(),
                    events=[], occurrences=[], expected_revision=source.revision)
        for value in ('["read","write"]', '["read"]'):
            await replace_window(**args, capabilities_json=value)
            assert (await calendar_source.get(source.id)).capabilities_json == value
        with pytest.raises(LostClaim):
            await replace_window(**{**args, "attempt": claim.attempts + 1}, capabilities_json='["read","write"]')
        assert (await calendar_source.get(source.id)).capabilities_json == '["read"]'
    asyncio.run(run())


def test_parallel_updates_on_one_event_one_call(pg_db, monkeypatch):
    async def run():
        import hashlib
        import json
        from uuid import uuid4
        from api.calendar import writes
        from api.mail import connectors
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_sync_state import CalendarSyncState
        source = CalendarSource(provider="google", connection_ref="google_calendar#" + hashlib.sha256(b"google_calendar:synthetic").hexdigest()[:16],
            external_id="synthetic", name="Example", timezone="UTC", capabilities_json='["read","write"]')
        event = CalendarEvent(source_id=source.id, external_id="synthetic-event")
        start = datetime(2026, 12, 5, 9, tzinfo=UTC)
        occurrence = CalendarOccurrence(source_id=source.id, event_id=event.id, external_id="synthetic-event",
            start_at=start, end_at=start + timedelta(hours=1), timezone="UTC", editable=True)
        async with get_session_maker()() as session:
            session.add_all([source, event, occurrence, CalendarSyncState(source_id=source.id,
                coverage_start=start - timedelta(days=1), coverage_end=start + timedelta(days=1))])
            await session.commit()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def fake(connector, tool, arguments, **kwargs):
            if tool == "list_events": return json.dumps({"summary": "synthetic", "events": []})
            raw = {"id": "synthetic-event", "summary": "Example", "updated": "old",
                   "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(hours=1)).isoformat()}}
            if tool == "update_event":
                calls.append(tool)
                entered.set()
                await release.wait()
                raw.update(summary="Changed", updated="new")
            return json.dumps(raw)
        monkeypatch.setattr(connectors, "_call_tool", fake)
        def request():
            return writes.WriteRequest(write_id=uuid4(), operation="update", source_id=source.id,
                occurrence_id=occurrence.id, expected_revision="old", title="Changed")
        first = asyncio.create_task(writes.execute(request()))
        await asyncio.wait_for(entered.wait(), 5)
        try:
            with pytest.raises(writes.WriteError, match="calendar_write_in_progress"):
                await writes.execute(request())
        finally:
            release.set()
        assert (await first).status == "done"
        assert calls == ["update_event"]
        from db.accessors import calendar_occurrence
        assert (await calendar_occurrence.get_visible(occurrence.id)).title == "Changed"
    asyncio.run(run())


def test_parallel_calendar_confirm_claims_once(pg_db, monkeypatch):
    async def run():
        import json
        from api.calendar import writes
        from api.calendar.proposals import CalendarCommand, CalendarValues
        from api.mail import proposals
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.chat_context import ChatContext
        from db.models.chat_message import ChatMessage
        source = CalendarSource(provider="google", connection_ref="synthetic", external_id="synthetic", name="Example",
                                timezone="UTC", capabilities_json='["read","write"]')
        context = ChatContext(conversation_id="synthetic-conversation", app_prompt_version="8", account_scope_json="{}",
                              calendar_scope_json=json.dumps([source.id]))
        command = CalendarCommand(action="create", source_id=source.id, connection_ref=source.connection_ref, timezone="UTC",
            after=CalendarValues(title="Example", start_date="2026-12-05", end_date="2026-12-06"))
        proposal = proposals.Proposal(kind="calendar", reason="Example", items=[], calendar=command)
        message = ChatMessage(conversation_id=context.conversation_id, context_id=context.id, role="proposal",
            proposal_json=proposal.model_dump_json(context={"storage": True}), proposal_status="pending")
        async with get_session_maker()() as session:
            session.add_all([source, context, message])
            await session.commit()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def execute(request, *, write_id):
            calls.append(write_id)
            entered.set()
            await release.wait()
            return writes.WriteOutcome(write_id=write_id, status="done")
        monkeypatch.setattr(writes, "execute", execute)
        first = asyncio.create_task(proposals.confirm(message.id, selected_ids=[]))
        await asyncio.wait_for(entered.wait(), 5)
        try:
            with pytest.raises(proposals.ProposalStateError):
                await proposals.confirm(message.id, selected_ids=[])
        finally:
            release.set()
        assert (await first).proposal_status == "done"
        assert calls == [message.id]
    asyncio.run(run())


def test_index_write_is_fenced_and_preserves_unrelated_masters(pg_db):
    async def run():
        from db.accessors import calendar_index_write, calendar_source
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_sync_state import CalendarSyncState
        source = CalendarSource(provider="google", connection_ref="synthetic", external_id="synthetic", name="Example", timezone="UTC")
        first = datetime(2026, 12, 5, tzinfo=UTC)
        event = CalendarEvent(source_id=source.id, external_id="target")
        unrelated = CalendarEvent(source_id=source.id, external_id="unexpanded-master")
        row = CalendarOccurrence(source_id=source.id, event_id=event.id, external_id="target", start_at=first,
                                 end_at=first + timedelta(hours=1), timezone="UTC", editable=True)
        async with get_session_maker()() as session:
            session.add_all([source, unrelated, CalendarSyncState(source_id=source.id, coverage_start=first,
                coverage_end=first + timedelta(days=1))])
            await session.commit()
        assert not await calendar_index_write.apply(source_id=source.id, upsert=(event, row), delete_external_id=None,
                                                    expected_revision=source.revision + 1)
        assert await calendar_index_write.find(source.id, row.external_id) is None
        assert await calendar_index_write.apply(source_id=source.id, upsert=(event, row), delete_external_id=None,
                                                expected_revision=source.revision)
        assert (await calendar_index_write.find(source.id, row.external_id)).editable
        await calendar_index_write.apply(source_id=source.id, upsert=None, delete_external_id=row.external_id)
        async with get_session_maker()() as session:
            assert await session.get(CalendarEvent, unrelated.id) is not None
            assert await session.get(CalendarEvent, event.id) is None
        await calendar_source.set_active(source.id, False)
        assert not await calendar_index_write.apply(source_id=source.id, upsert=(event, row), delete_external_id=None)
    asyncio.run(run())


def test_seed_create_update_delete_never_calls_connector(pg_db, monkeypatch):
    async def run():
        from uuid import uuid4
        from api.calendar import writes
        from api.mail import connectors
        from api.mail.seed_ids import seed_id
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState
        source = CalendarSource(id=seed_id("calendar", "work"), provider="google", connection_ref="synthetic", external_id="synthetic",
            name="Example", timezone="UTC", capabilities_json='["read","write"]')
        async with get_session_maker()() as session:
            session.add_all([source, CalendarSyncState(source_id=source.id,
                coverage_start=datetime(2026, 12, 1, tzinfo=UTC), coverage_end=datetime(2027, 1, 1, tzinfo=UTC))])
            await session.commit()
        async def forbidden(*args, **kwargs):
            pytest.fail("Seed must not call a connector")
        monkeypatch.setattr(connectors, "_call_tool", forbidden)
        created = await writes.execute(writes.WriteRequest(write_id=uuid4(), source_id=source.id, operation="create",
            title="Example", start_date="2026-12-05", end_date="2026-12-06", description="Example description"))
        assert created.status == "done" and created.occurrence_id
        detail = await writes.live(created.occurrence_id)
        assert detail.editable and detail.description == "Example description"
        updated = await writes.execute(writes.WriteRequest(write_id=uuid4(), source_id=source.id, operation="update",
            occurrence_id=created.occurrence_id, expected_revision=detail.revision, title="Changed"))
        assert updated.status == "done"
        deleted = await writes.execute(writes.WriteRequest(write_id=uuid4(), source_id=source.id, operation="delete",
            occurrence_id=created.occurrence_id, expected_revision=updated.revision))
        assert deleted.status == "done"
    asyncio.run(run())


def test_terminal_write_cannot_be_overwritten_by_a_late_check(pg_db):
    async def run():
        from db.accessors.calendar_write import claim, finish
        row = write_row()
        await claim(row)
        await finish(row.id, status="done", result_external_id="synthetic-event")
        result = await finish(row.id, status="unknown", error_code="calendar_write_unknown")
        assert result.status == "done" and result.error_code is None
    asyncio.run(run())


def write_row(**changes):
    from db.models.calendar_write import CalendarWrite
    from uuid import uuid4
    return CalendarWrite(**{**dict(id=str(uuid4()), source_id="synthetic-source", operation="update",
                                  target_external_id="synthetic-event", request_json='{"title":"Example"}',
                                  request_hash="synthetic-hash", status="running"), **changes})


def test_claim_is_idempotent_for_same_hash(pg_db):
    async def run():
        from db.accessors.calendar_write import claim
        row = write_row()
        assert (await claim(row))[1]
        existing, created = await claim(row)
        assert existing.id == row.id and not created
    asyncio.run(run())


def test_claim_conflicts_on_other_hash(pg_db):
    async def run():
        from db.accessors.calendar_write import claim, WriteConflict
        row = write_row()
        await claim(row)
        with pytest.raises(WriteConflict):
            await claim(write_row(id=row.id, request_hash="other"))
    asyncio.run(run())


def test_second_running_write_on_target_is_refused(pg_db):
    async def run():
        from db.accessors.calendar_write import claim, WriteInProgress
        results = await asyncio.gather(claim(write_row()), claim(write_row()), return_exceptions=True)
        assert sum(isinstance(r, WriteInProgress) for r in results) == 1
        assert sum(isinstance(r, tuple) and r[1] for r in results) == 1
    asyncio.run(run())


@pytest.mark.parametrize("status", ["done", "failed", "not_applied", "unknown"])
def test_finish_clears_request_text_on_final_states(pg_db, status):
    async def run():
        from db.accessors.calendar_write import claim, finish
        row = write_row()
        await claim(row)
        result = await finish(row.id, status=status)
        assert (result.request_json is None) == (status != "unknown")
        assert result.finished_at is not None
    asyncio.run(run())


def test_expire_running_only_after_threshold(pg_db):
    async def run():
        from db.accessors.calendar_write import claim, expire_running
        now = datetime.now(UTC)
        row = write_row(started_at=now)
        await claim(row)
        assert (await expire_running(row.id, before=now)).status == "running"
        assert (await expire_running(row.id, before=now + timedelta(seconds=1))).status == "unknown"
        assert (await expire_running(row.id, before=now + timedelta(days=1))).status == "unknown"
    asyncio.run(run())


def test_mark_dispatch_only_while_running_and_refreshes_the_clock(pg_db):
    async def run():
        from db.accessors.calendar_write import claim, expire_running, get, mark_dispatch
        old = datetime.now(UTC) - timedelta(seconds=30)
        row = write_row(started_at=old)
        await claim(row)
        assert await mark_dispatch(row.id) is True
        assert (await get(row.id)).started_at > old
        expired = write_row(target_external_id="synthetic-other", started_at=old)
        await claim(expired)
        await expire_running(expired.id, before=datetime.now(UTC))
        assert await mark_dispatch(expired.id) is False
        assert (await get(expired.id)).status == "unknown"
    asyncio.run(run())


def test_remove_source_keeps_open_outcomes_without_text(pg_db):
    async def run():
        from db.accessors import calendar_write, calendar_source
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        running, unknown, done = write_row(), write_row(target_external_id="synthetic-b"), write_row(target_external_id="synthetic-c")
        async with get_session_maker()() as session:
            session.add(CalendarSource(id=running.source_id, provider="google", connection_ref="synthetic", external_id="synthetic", name="Example", timezone="UTC"))
            await session.commit()
        for row in (running, unknown, done):
            await calendar_write.claim(row)
        await calendar_write.finish(unknown.id, status="unknown", error_code="calendar_write_unknown")
        await calendar_write.finish(done.id, status="done", result_external_id="synthetic-c")
        await calendar_source.remove(running.source_id)
        # The provider may have applied an open write: its record must keep saying so, without text.
        for row in (running, unknown):
            kept = await calendar_write.get(row.id)
            assert kept.status == "unknown" and kept.request_json is None
        assert await calendar_write.get(done.id) is None
    asyncio.run(run())
