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
        _, legacy_context, _ = await resolve(legacy.id)
        assert legacy_context.calendar_scope_json == '[]'
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
