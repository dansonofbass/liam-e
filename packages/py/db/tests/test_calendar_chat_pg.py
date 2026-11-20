"""Live calendar-scope provenance and model-history isolation contracts."""
import asyncio
import copy
import json
import os
from types import SimpleNamespace as NS

import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


def test_calendar_scope_and_model_history_isolation(pg_db, monkeypatch):
    async def run():
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.accessors import chat_context, chat_message, chat_conversation, calendar_source
        from api.mail import agent
        from fastapi import HTTPException

        sources = [CalendarSource(provider='synthetic', connection_ref='test-only', external_id=key,
            name=key, timezone='UTC', capabilities_json='["read"]') for key in ('work', 'private')]
        async with get_session_maker()() as session:
            session.add_all(sources)
            await session.commit()
        ids = [s.id for s in sources]
        async def resolve(id=None, scope=None):
            return await chat_context.resolve(conversation_id=id, title='Test', model='', revision_id=None,
                account_id=None, app_prompt_version='test', calendar_source_ids=scope or [])
        conversation, snapshot, _ = await resolve(scope=ids)
        assert json.loads(snapshot.calendar_scope_json) == sorted(ids)
        for role in ('user', 'tool', 'assistant'):
            await chat_message.add_message(conversation_id=conversation.id, role=role,
                content='test-only foreign calendar marker', context_id=snapshot.id)
        requests = []
        class Stream:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def __aiter__(self):
                yield NS(data=NS(choices=[NS(delta=NS(content='Antwort', tool_calls=None))]))
        class Chat:
            async def stream_async(self, **kwargs):
                requests.append(copy.deepcopy(kwargs))
                return Stream()
        monkeypatch.setattr(agent, 'mistral_client', lambda: NS(chat=Chat()))
        for scope in ([], [ids[0]], [ids[1]]):
            with pytest.raises(HTTPException) as error:
                _ = [e async for e in agent.run_turn_events(conversation_id=conversation.id, text='Weiter', calendar_source_ids=scope)]
            assert error.value.status_code == 409
            assert requests == []
        # Even expansion starts fresh; never reinterpret provenance of older user/assistant text.
        single, single_context, _ = await resolve(scope=[ids[0]])
        await chat_message.add_message(conversation_id=single.id, role='user', content='Test', context_id=single_context.id)
        with pytest.raises(chat_context.ScopeChange): await resolve(single.id, ids)
        legacy = await chat_conversation.create_conversation()
        await chat_message.add_message(conversation_id=legacy.id, role='assistant', content='Unbelegter Altverlauf')
        with pytest.raises(chat_context.ScopeChange): await resolve(legacy.id, ids)
        with pytest.raises(chat_context.ScopeChange): await resolve(legacy.id)
        events = [e async for e in agent.run_turn_events(conversation_id=None, text='Neue Frage', calendar_source_ids=[ids[0]])]
        assert events[-1].event == 'done'
        assert len(requests) == 1
        assert 'foreign calendar marker' not in json.dumps(requests)
        assert 'Unbelegter Altverlauf' not in json.dumps(requests)
        assert len(await chat_message.list_messages(conversation.id)) == 3
        await calendar_source.set_active(ids[0], False)
        assert not await chat_context.is_live(snapshot.id)
        with pytest.raises(chat_context.ScopeChange): await resolve(conversation.id, ids)
        await calendar_source.remove(ids[1])
        with pytest.raises(ValueError): await resolve(scope=[ids[1]])
    asyncio.run(run())


def test_calendar_seed_roundtrip_and_repeatability(pg_db, monkeypatch):
    async def run():
        from datetime import UTC, datetime
        from api.mail.dev_seed import seed_calendars
        from db.accessors import calendar_source, calendar_occurrence
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        outsider = CalendarSource(provider='synthetic', connection_ref='test-only', external_id='other', name='Other', timezone='UTC')
        async with get_session_maker()() as session:
            session.add(outsider)
            await session.commit()
        for _ in range(2):
            await seed_calendars(datetime(2026, 11, 13, 12, tzinfo=UTC))
        assert len(await calendar_source.list_all()) == 6
        assert await calendar_source.get(outsider.id) is not None
        from api.mail.seed_ids import seed_id
        assert await calendar_occurrence.get_visible(seed_id('calendar-occurrence', 'work')) is not None
        assert await calendar_occurrence.get_visible(seed_id('calendar-occurrence', 'paused')) is None
    asyncio.run(run())


def test_automatic_calendar_scope_and_coverage_beyond_fifty_sources(pg_db):
    async def run():
        from datetime import UTC, date, datetime, timedelta
        from db.accessors import calendar_source, chat_context, chat_message
        from db.engine import get_session_maker
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState
        from api.mail.calendar_tools import read_calendar

        async def resolve(conversation_id=None, scope=None):
            return await chat_context.resolve(conversation_id=conversation_id, title='Test', model='',
                revision_id=None, account_id=None, app_prompt_version='test', calendar_source_ids=scope)

        async def search(ids):
            result, _ = await read_calendar('search_calendar', {'from': '2026-11-12', 'to': '2026-11-14'}, ids, 'UTC')
            return result

        def source(key, **options):
            return CalendarSource(id=key, provider='ics', connection_ref='test-only', external_id=key,
                                  name=key, timezone='UTC', **options)

        _, empty, _ = await resolve()
        assert json.loads(empty.calendar_scope_json) == []
        assert not (await search([]))['index_complete_for_window']
        readable = [source(f'test-{n:02}', capabilities_json='["read"]') for n in range(52)]
        paused = source('paused-private', capabilities_json='["read"]', is_active=False)
        denied = source('denied-private', capabilities_json='[]')
        gone = source('reconnect-private', capabilities_json='["read"]')
        maker = get_session_maker()
        async with maker.begin() as session:
            session.add(readable[0])
        conversation, single, _ = await resolve()
        assert json.loads(single.calendar_scope_json) == [readable[0].id]
        await chat_message.add_message(conversation_id=conversation.id, context_id=single.id, role='user', content='Test')
        async with maker.begin() as session:
            session.add_all([*readable[1:], paused, denied, gone])
            await session.flush()
            session.add(CalendarSyncState(source_id=gone.id, last_error='reconnect_required'))
            session.add(CalendarOccurrence(source_id=readable[-1].id, event_id='synthetic-event', external_id='test',
                title='Last source', start_date=date(2026, 11, 13), end_date=date(2026, 11, 14)))
            session.add(CalendarOccurrence(source_id=readable[0].id, event_id='synthetic-multiday', external_id='test-span',
                title='Ongoing', start_date=date(2026, 11, 10), end_date=date(2026, 11, 13)))
        with pytest.raises(chat_context.ScopeChange):
            await resolve(conversation.id)
        _, snapshot, _ = await resolve()
        ids = json.loads(snapshot.calendar_scope_json)
        assert ids == [item.id for item in readable]
        _, narrow, _ = await resolve(scope=[])
        assert json.loads(narrow.calendar_scope_json) == []
        with pytest.raises(ValueError):
            await resolve(scope=[denied.id])
        result = await search(ids)
        assert result['source_count'] == 52
        assert not result['index_complete_for_window']
        assert result['unavailable_source_counts'] == {'paused': 1, 'disconnected': 1, 'unreadable': 1}
        assert not any(item.id in json.dumps(result) for item in (paused, denied, gone))
        assert [event['title'] for event in result['untrusted_calendar_data']['occurrences']] == ['Ongoing', 'Last source']

        now = datetime.now(UTC)
        async with maker.begin() as session:
            for item in readable:
                session.add(CalendarSyncState(source_id=item.id, incomplete=False, last_success_at=now,
                    coverage_start=datetime(2026, 11, 12, tzinfo=UTC), coverage_end=datetime(2026, 11, 14, tzinfo=UTC)))
        assert (await search(ids))['index_complete_for_window']
        async with maker.begin() as session:
            state = await session.get(CalendarSyncState, readable[-1].id)
            state.last_success_at = now - timedelta(days=2)
        assert not (await search(ids))['index_complete_for_window']
        await calendar_source.set_active(readable[-1].id, False)
        assert not await chat_context.is_live(snapshot.id)
        assert (await search(ids))['error'] == 'calendar_scope_revoked'
        await calendar_source.remove(readable[0].id)
        _, remaining, _ = await resolve()
        assert json.loads(remaining.calendar_scope_json) == ids[1:-1]
    asyncio.run(run())


def test_calendar_default_revision_and_proposal_target(pg_db, monkeypatch):
    async def run():
        from dataclasses import replace
        from datetime import date
        from db.accessors import calendar_settings, calendar_source
        from db.accessors.prompt_template import StaleVersion
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from api.calendar import chat, writes
        from api.mail import proposals
        from api.mail.agent_tools import TurnContext
        from db.accessors import chat_context

        def source(key, name, provider='google', write=True):
            return CalendarSource(id=key, provider=provider, connection_ref='test-only', external_id=key, name=name,
                                  timezone='UTC', capabilities_json='["read","write"]' if write else '["read"]')

        first, second = source('primary', 'Team'), source('secondary', 'Privat')
        feed, twin = source('ics', 'Ferien', 'ics', False), source('twin', 'Team')
        paused = source('paused-research', 'Research')
        paused.is_active = False
        async with get_session_maker().begin() as session:
            session.add_all([first, second, feed, twin, paused])
        conversation, snapshot, _ = await chat_context.resolve(conversation_id=None, title='Test', model='',
            revision_id=None, account_id=None, app_prompt_version='test')
        ctx = TurnContext(conversation.id, None, date(2026, 11, 12), context_id=snapshot.id,
                          calendar_source_ids=json.loads(snapshot.calendar_scope_json))
        values = {'action': 'create', 'title': 'Test', 'start_date': '2026-11-13', 'end_date': '2026-11-14'}
        assert (await calendar_settings.get()).default_source_id is None
        with pytest.raises(writes.WriteError, match='calendar_default_missing'):
            await chat.prepare(values, ctx)
        with pytest.raises(calendar_settings.CalendarNotWritable):
            await calendar_settings.update(1, feed.id)
        race = await asyncio.gather(*(calendar_settings.update(1, s.id) for s in (first, second)), return_exceptions=True)
        assert sum(isinstance(item, StaleVersion) for item in race) == 1
        chosen = await calendar_settings.get()
        assert chosen.version == 2 and chosen.default_source_id in {first.id, second.id}
        card = await chat.prepare(values, ctx)
        assert card.source_id == chosen.default_source_id
        from api.calendar.chat_target import choice_for_clarification
        assert paused.id not in ctx.calendar_source_ids
        pending = await choice_for_clarification(replace(ctx, user_text='Schedule a review in the Research calendar'), 'What time?')
        assert pending and pending.name.casefold() == 'research'
        with pytest.raises(writes.WriteError, match='calendar_name_unknown'):
            await chat.prepare(values, replace(ctx, calendar_choice=pending, user_text='Tomorrow at 10.'))
        dispatched = []
        async def execute(request, *, write_id):
            dispatched.append((request.source_id, write_id))
            return writes.WriteOutcome(write_id=write_id, status='done')
        monkeypatch.setattr(writes, 'execute', execute)
        saved = await proposals.create_proposal(conversation.id,
            proposals.Proposal(kind='calendar', reason='Test', items=[], calendar=card), context_id=snapshot.id)
        other = first if chosen.default_source_id == second.id else second
        await calendar_settings.update(2, other.id)
        async with get_session_maker().begin() as session:
            session.add(source('newly-connected', 'Additional'))
        assert await chat_context.is_live(snapshot.id)
        assert saved.proposal_status == 'pending' and dispatched == []
        assert (await proposals.confirm(saved.id, selected_ids=[])).proposal_status == 'done'
        with pytest.raises(proposals.ProposalStateError):
            await proposals.confirm(saved.id, selected_ids=[])
        assert dispatched == [(chosen.default_source_id, saved.id)]
        assert (await chat.prepare(values, ctx)).source_id == other.id
        named = replace(ctx, user_text='Bitte im Kalender PRIVAT eintragen')
        explicit = await chat.prepare({**values, 'calendar_name': 'Privat'}, named)
        assert explicit.source_id == second.id
        with pytest.raises(writes.WriteError, match='calendar_name_required'):
            await chat.prepare({**values, 'calendar_name': 'Team'}, named)
        for name, code in [('Team', 'calendar_name_ambiguous'), ('Wunsch', 'calendar_name_unknown'), ('Ferien', 'calendar_not_writable')]:
            named = replace(ctx, user_text=f'Bitte in {name} eintragen')
            with pytest.raises(writes.WriteError, match=code):
                await chat.prepare({**values, 'calendar_name': name}, named)
            with pytest.raises(writes.WriteError, match=code):
                await chat.prepare(values, named)
        with pytest.raises(writes.WriteError, match='calendar_name_required'):
            await chat.prepare({**values, 'source_id': chosen.default_source_id}, ctx)
        later = await proposals.create_proposal(conversation.id,
            proposals.Proposal(kind='calendar', reason='Test', items=[], calendar=await chat.prepare(values, ctx)),
            context_id=snapshot.id)
        await calendar_source.set_active(other.id, False)
        with pytest.raises(proposals.ProposalContextRevokedError):
            await proposals.confirm(later.id, selected_ids=[])
        assert dispatched == [(chosen.default_source_id, saved.id)]
        with pytest.raises(writes.WriteError, match='calendar_not_writable'):
            await chat.prepare(values, ctx)
        await calendar_source.remove(other.id)
        assert (await calendar_settings.get()).default_source_id == other.id
        ctx.calendar_source_ids.remove(other.id)
        with pytest.raises(writes.WriteError, match='calendar_default_unavailable'):
            await chat.prepare(values, ctx)
        assert (await calendar_settings.update(3, None)).default_source_id is None
    asyncio.run(run())


def test_missing_explicit_event_rejected_before_either_chat_endpoint_calls_model(pg_db, monkeypatch):
    async def run():
        from datetime import date
        from fastapi import HTTPException
        from sqlalchemy import func, select
        from db.accessors import calendar_source
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_occurrence import CalendarOccurrence
        from db.models.chat_conversation import ChatConversation
        from api.mail import agent
        from api.routers.api.v1.chat.route import ChatTurnRequest, chat_turn
        from api.routers.api.v1.chat.stream import ChatStreamRequest, chat_stream

        make = get_session_maker()
        async with make.begin() as session:
            for key in ('a', 'b'):
                session.add(CalendarSource(id=key, provider='google', name=key, connection_ref='test',
                                           external_id=key, capabilities_json='["read"]', timezone='UTC'))
            session.add(CalendarOccurrence(id='selected', source_id='a', event_id='event', external_id='event',
                                          start_date=date(2026, 11, 13), end_date=date(2026, 11, 14)))
        await calendar_source.set_active('a', False)
        assert await calendar_source.readable_ids(None) == ['b']
        monkeypatch.setattr(agent, 'mistral_client', lambda: pytest.fail('unexpected model call'))
        for occurrence_id in ('selected', 'absent'):
            args = {'context_occurrence_id': occurrence_id}
            for call in (lambda: chat_turn(ChatTurnRequest(message='This event?', **args)),
                         lambda: chat_stream(ChatStreamRequest(text='This event?', **args), NS())):
                with pytest.raises(HTTPException) as error:
                    await call()
                assert error.value.status_code == 404
                assert error.value.detail['code'] == 'calendar_reference_unavailable'
        async with make() as session:
            assert not await session.scalar(select(func.count()).select_from(ChatConversation))
    asyncio.run(run())
