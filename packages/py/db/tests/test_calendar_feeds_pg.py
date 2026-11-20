"""Live PostgreSQL contracts for private feed storage and configuration fencing."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_proof_consume_context_configuration_expiry_and_race(pg_db):
    async def run():
        from db.accessors import calendar_feed_validation as proofs
        from db.engine import get_session_maker
        from db.models.calendar_feed_validation import CalendarFeedValidation

        now = datetime(2026, 1, 1, tzinfo=UTC)
        row = CalendarFeedValidation(token_digest="test-only", context_id="installation",
                                     config_digest="configuration", encrypted_payload="test-only",
                                     expires_at=now + timedelta(minutes=10))
        async with get_session_maker()() as session:
            session.add(row)
            await session.commit()

        async def consume(context="installation", config="configuration", at=now):
            async with get_session_maker()() as session:
                result = await proofs.consume(session, token_digest=row.token_digest,
                                              context_id=context, config_digest=config, now=at)
                await session.commit()
                return result

        assert await consume(context="other") is None
        assert await consume(config="changed") is None
        # Separate connections contend for the same row; exactly one transaction wins.
        results = await asyncio.gather(consume(), consume())
        assert sum(result is not None for result in results) == 1
        assert await consume() is None
        async with get_session_maker()() as session:
            session.add(CalendarFeedValidation(token_digest="expired", context_id="installation",
                                               config_digest="configuration", encrypted_payload="test-only",
                                               expires_at=now))
            await session.commit()
        async with get_session_maker()() as session:
            assert await proofs.consume(session, token_digest="expired", context_id="installation",
                                        config_digest="configuration", now=now) is None
            await proofs.purge_expired(session, now=now)
            await session.commit()
            assert not (await session.execute(select(CalendarFeedValidation))).scalars().all()
    asyncio.run(run())


def test_proof_consumption_rolls_back_with_subscription(pg_db):
    async def run():
        from db.accessors import calendar_feed_validation as proofs
        from db.engine import get_session_maker
        from db.models.calendar_feed_validation import CalendarFeedValidation

        now = datetime(2026, 1, 1, tzinfo=UTC)
        async with get_session_maker()() as session:
            session.add(CalendarFeedValidation(token_digest="rollback", context_id="installation",
                                               config_digest="configuration", encrypted_payload="test-only",
                                               expires_at=now + timedelta(minutes=10)))
            await session.commit()
        args = dict(token_digest="rollback", context_id="installation", config_digest="configuration", now=now)
        async with get_session_maker()() as session:
            assert await proofs.consume(session, **args) is not None
            await session.rollback()
        async with get_session_maker()() as session:
            assert await proofs.consume(session, **args) is not None
            await session.commit()
    asyncio.run(run())


def test_snapshot_fences_configuration_pause_resume_and_removal(pg_db):
    async def run():
        from db.accessors import calendar_source, mail_job
        from db.accessors.calendar_snapshot import LostClaim, replace_window
        from db.engine import get_session_maker
        from db.models.calendar_feed_config import CalendarFeedConfig
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState

        source = CalendarSource(provider="ics", connection_ref="opaque", external_id="feed",
                                name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add_all([source, CalendarFeedConfig(source_id=source.id, encrypted_payload="test-only")])
            await session.commit()
        job = await mail_job.enqueue("calendar_sync", {"source_id": source.id},
                                     dedupe_key=f"calendar_sync:{source.id}")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        args = dict(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                    start=start, end=end, start_date=start.date(), end_date=end.date(),
                    events=[], occurrences=[], expected_revision=source.revision)
        await calendar_source.set_active(source.id, False)
        await calendar_source.set_active(source.id, True)
        with pytest.raises(LostClaim):
            await replace_window(**args)
        async with get_session_maker()() as session:
            assert await session.get(CalendarSyncState, source.id) is None
        args["expected_revision"] = (await calendar_source.get(source.id)).revision
        await replace_window(**args)
        # Actual competing transactions: either the commit precedes deletion or
        # the worker loses its source lock. Neither order may resurrect rows.
        result, removed = await asyncio.gather(replace_window(**args), calendar_source.remove(source.id),
                                               return_exceptions=True)
        assert result is None or isinstance(result, LostClaim)
        assert removed is True
        with pytest.raises(LostClaim):
            await replace_window(**args)
        async with get_session_maker()() as session:
            assert await session.get(CalendarFeedConfig, source.id) is None
            assert await session.get(CalendarSyncState, source.id) is None
    asyncio.run(run())


def test_chat_history_is_bound_to_one_feed_configuration_across_retries_and_replacement(pg_db, monkeypatch):
    async def run():
        from fastapi import HTTPException
        from db.accessors import calendar_feed_subscription, calendar_feed_sync, calendar_source, chat_context, chat_message, mail_job
        from db.accessors.calendar_snapshot import replace_window
        from db.engine import get_session_maker
        from db.models.calendar_event import CalendarEvent
        from db.models.calendar_feed_validation import CalendarFeedValidation
        from db.models.calendar_occurrence import CalendarOccurrence
        from api.mail import agent
        from api.routers.api.v1.chat.history import history

        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        async def subscribe(token, previous=None):
            async with get_session_maker().begin() as session:
                session.add(CalendarFeedValidation(token_digest=token, context_id='test', config_digest=token,
                    encrypted_payload=f'synthetic-sealed-{token}', expires_at=now + timedelta(hours=1)))
            return await calendar_feed_subscription.subscribe(token_digest=token, context_id='test', config_digest=token,
                now=now, name='Calendar', timezone='UTC', source_id=previous.id if previous else None,
                expected_revision=previous.revision if previous else None)

        async def publish(source, title):
            claim = await mail_job.claim_next(now + timedelta(minutes=5), stale_after=timedelta(minutes=10))
            event = CalendarEvent(source_id=source.id, external_id='same-event-id', title=title)
            occurrence = CalendarOccurrence(source_id=source.id, event_id=event.id, external_id='same-occurrence-id',
                                           title=title, start_date=start.date(), end_date=end.date())
            await replace_window(source_id=source.id, job_id=claim.id, attempt=claim.attempts, start=start, end=end,
                start_date=start.date(), end_date=end.date(), events=[event], occurrences=[occurrence],
                expected_revision=source.revision, replace_all=True, reset_schedule=True)
            await mail_job.finish(claim.id, claim.attempts)

        async def resolve(conversation=None):
            return await chat_context.resolve(conversation_id=conversation, title='Test', model='', revision_id=None,
                                             account_id=None, app_prompt_version='test')

        first = await subscribe('feed-a')
        await publish(first, 'A only')
        conversation, snapshot, _ = await resolve()
        await chat_message.add_message(conversation_id=conversation.id, context_id=snapshot.id, role='assistant', content='A only')
        card = await chat_message.add_message(conversation_id=conversation.id, context_id=snapshot.id,
                                              role='proposal', proposal_status='pending',
                                              proposal_json='{"kind":"archive","reason":"Test","items":[]}')
        await calendar_feed_sync.failure(first.id, revision=first.revision, now=now, code='address_check', delay_seconds=None)
        assert not await chat_context.is_live(snapshot.id)
        assert await calendar_feed_sync.enqueue(first.id, now=now + timedelta(minutes=2), interval=5, manual=True)
        await publish(first, 'A only')
        assert await chat_context.is_live(snapshot.id)
        await resolve(conversation.id)

        second = await subscribe('feed-b', first)
        assert second.id == first.id and not await chat_context.is_live(snapshot.id)
        await publish(second, 'B only')
        assert await calendar_source.readable_ids(None) == [first.id]
        assert not await chat_context.is_live(snapshot.id)
        assert await chat_message.claim_proposal(card.id) is None
        monkeypatch.setattr(agent, 'mistral_client', lambda: pytest.fail('old feed data must not reach the model'))
        with pytest.raises(HTTPException) as error:
            _ = [e async for e in agent.run_turn_events(conversation_id=conversation.id, text='Continue')]
        assert error.value.detail['code'] == 'conversation_scope_change_requires_new'
        # A plain historical answer can be shown to the owner with its expired context.
        await chat_message.cancel_open_proposals(conversation.id)
        rows = await history(conversation.id)
        assert rows[0].context.calendar_sources_replaced
        assert 'calendar_feed_bindings' not in rows[0].model_dump_json()
        _, fresh, _ = await resolve()
        assert fresh.calendar_scope_json == snapshot.calendar_scope_json
        assert await chat_context.is_live(fresh.id)
    asyncio.run(run())
