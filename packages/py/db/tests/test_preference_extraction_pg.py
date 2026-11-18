"""Opt-in, once-only delivery and suppression on real PostgreSQL transactions."""
import asyncio
import os
from types import SimpleNamespace
import pytest
from db.engine import get_session_maker
from db.accessors import preference_extraction as ex, personalization_settings as settings
from db.accessors import preference_candidate as candidates, user_preference as preferences
from db.models.chat_conversation import ChatConversation
from db.models.chat_message import ChatMessage

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')
ITEM = SimpleNamespace(key='answer_length', scope='global', value='Kurz')


async def source(content='Bitte antworte künftig kurz.', role='user'):
    async with get_session_maker()() as session:
        conversation = ChatConversation()
        message = ChatMessage(conversation_id=conversation.id, role=role, content=content)
        session.add_all([conversation, message])
        await session.commit()
        return conversation.id, message.id


async def toggle(**changes):
    row = await settings.settings()
    return await settings.update_settings(row.version, **changes)


async def rows():
    async with get_session_maker()() as session:
        return await candidates.list_rows(session)


def test_activation_boundaries_and_independent_switches(pg_db):
    async def run():
        initial = await settings.settings()
        assert not initial.use_preferences and not initial.suggest_preferences
        old = await source()
        enabled = await toggle(suggest_preferences=True)
        assert enabled.suggestion_activation and not enabled.use_preferences
        assert await ex.claim(*old, 1) is None
        new = await source()
        assert await ex.claim(*new, 1)
        await toggle(suggest_preferences=False, use_preferences=True)
        gap = await source()
        again = await toggle(suggest_preferences=True)
        assert again.use_preferences and again.suggestion_activation != enabled.suggestion_activation
        assert await ex.claim(*gap, 1) is None
        assert await ex.claim(*new, 2) is None
    asyncio.run(run())


def test_concurrent_claims_and_results_store_only_one_set(pg_db):
    async def run():
        await toggle(suggest_preferences=True)
        ids = await source()
        claims = await asyncio.gather(ex.claim(*ids, 1), ex.claim(*ids, 1))
        assert sum(c is not None for c in claims) == 1
        activation, _ = next(c for c in claims if c)
        await asyncio.gather(ex.store(*ids, 1, activation, [ITEM]), ex.store(*ids, 1, activation, [ITEM]))
        result = await rows()
        assert len(result) == 1 and result[0].origin == 'extractor'
        assert result[0].source_message_id == ids[1] and result[0].proposal_id is None
        assert not (await settings.settings()).use_preferences
        assert await preferences.list_preferences() == []
        assert await ex.claim(*ids, 1) is None
        # Another extractor version can claim, but exact duplicate candidates are suppressed.
        activation2, _ = await ex.claim(*ids, 2)
        await ex.store(*ids, 2, activation2, [ITEM])
        assert len(await rows()) == 1
    asyncio.run(run())


@pytest.mark.parametrize('reenable', [False, True])
def test_disable_during_model_call_discards_results(pg_db, reenable):
    async def run():
        await toggle(suggest_preferences=True)
        ids = await source()
        activation, _ = await ex.claim(*ids, 1)
        await toggle(suggest_preferences=False)
        if reenable:
            await toggle(suggest_preferences=True)
        await ex.store(*ids, 1, activation, [ITEM])
        assert await rows() == []
    asyncio.run(run())


def test_rejection_deletion_and_fresh_explicit_request(pg_db):
    async def run():
        await toggle(suggest_preferences=True)
        ids = await source()
        activation, _ = await ex.claim(*ids, 1)
        await ex.store(*ids, 1, activation, [ITEM])
        row = (await rows())[0]
        async with get_session_maker()() as session:
            await preferences.lock(session)
            await candidates.erase(session, await candidates.get(session, row.id), 'rejected')
            await session.commit()
        activation, _ = await ex.claim(*ids, 2)
        await ex.store(*ids, 2, activation, [ITEM])
        assert await rows() == []
        deleted_source = await source()
        activation, _ = await ex.claim(*deleted_source, 1)
        pref = await preferences.create(key='answer_length', value='Kurz')
        await preferences.change(pref.id, 1, delete=True)
        with pytest.raises(candidates.CandidateGone):
            await ex.store(*deleted_source, 1, activation, [ITEM])
        # The unchanged #39 path still permits a new explicit request.
        from api.preferences.candidates import prepare
        from api.mail.agent_tools import TurnContext
        from datetime import date
        fresh = await source('Merke dir: Antworte kurz.')
        ctx = TurnContext(fresh[0], None, date.today(), account_ids=[], source_message_id=fresh[1])
        row, card = await prepare({'source_message_id': fresh[1], 'key': 'answer_length', 'value': 'Kurz'}, ctx)
        assert row.origin == 'explicit' and card is not None
    asyncio.run(run())


@pytest.mark.parametrize('role', ['assistant', 'tool'])
def test_other_roles_never_claimed(pg_db, role):
    async def run():
        await toggle(suggest_preferences=True)
        with pytest.raises(candidates.CandidateGone):
            await ex.claim(*(await source(role=role)), 1)
    asyncio.run(run())


def test_long_and_removed_sources_never_claimed(pg_db):
    async def run():
        await toggle(suggest_preferences=True)
        assert await ex.claim(*(await source('x' * 2001)), 1) is None
        ids = await source()
        activation, _ = await ex.claim(*ids, 1)
        async with get_session_maker()() as session:
            await session.delete(await session.get(ChatMessage, ids[1]))
            await session.commit()
        with pytest.raises(candidates.CandidateGone):
            await ex.store(*ids, 1, activation, [ITEM])
        assert await rows() == []
    asyncio.run(run())
