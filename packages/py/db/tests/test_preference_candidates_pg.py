"""Live transaction tests for candidates, not model or prompt simulations."""
import asyncio
import os
import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


async def setup_source(role='user'):
    from db.engine import get_session_maker
    from db.models.chat_conversation import ChatConversation
    from db.models.chat_message import ChatMessage
    async with get_session_maker()() as session:
        conversation = ChatConversation()
        message = ChatMessage(conversation_id=conversation.id, role=role, content='Merke dir: Antworte kurz.')
        session.add_all([conversation, message])
        await session.commit()
        return conversation, message


async def candidate(conversation, message, **kwargs):
    from db.engine import get_session_maker
    from db.accessors import preference_candidate as c, user_preference as p
    async with get_session_maker()() as session:
        await p.lock(session)
        row = await c.create(session, conversation_id=conversation.id, source_message_id=message.id,
                             key='answer_length', scope='*', value=kwargs.get('value', 'Kurz'))
        card = await c.open_card(session, row)
        await session.commit()
        return row, card


async def confirm(row, card, decision='replace'):
    from db.engine import get_session_maker
    from db.accessors import preference_candidate as c, user_preference as p, chat_message as m
    async with get_session_maker()() as session:
        await p.lock(session)
        claimed = await m.claim_proposal_in_session(session, card.id)
        if claimed is None:
            return 'not_pending'
        current = await c.get(session, row.id)
        result = await c.accept(session, current, decision=decision,
                                expected_version=row.expected_version, expected_revision_id=row.expected_revision_id)
        await m.finish_proposal_in_session(session, card.id, proposal_json=card.proposal_json)
        await session.commit()
        return result


def test_concurrent_confirm_one_revision_and_use_stays_off(pg_db):
    async def run():
        from db.accessors import user_preference as p
        conversation, message = await setup_source()
        row, card = await candidate(conversation, message)
        assert await p.list_preferences() == []
        results = await asyncio.gather(confirm(row, card), confirm(row, card))
        assert sorted(results) == ['not_pending', 'saved']
        assert len(await p.list_preferences()) == 1
        assert not (await p.settings()).use_preferences
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['send', 'task', 'archive'])
def test_existing_card_is_preserved_and_double_click_idempotent(pg_db, kind):
    async def run():
        from db.accessors import chat_message as m
        conversation, message = await setup_source()
        old = await m.add_message(conversation_id=conversation.id, role='proposal', proposal_status='pending',
                                  proposal_json='{"kind":"' + kind + '"}')
        row, card = await candidate(conversation, message)
        assert card is None
        assert (await m.get_message(old.id)).proposal_status == 'pending'
        await m.cancel_proposal(old.id)
        results = await asyncio.gather(candidate(conversation, message), candidate(conversation, message))
        assert results[0][0].id == results[1][0].id == row.id
        assert results[0][1].id == results[1][1].id
    asyncio.run(run())


def test_stale_confirm_rolls_back_claim_and_exact_noop(pg_db):
    async def run():
        from db.accessors import user_preference as p, preference_candidate as c, chat_message as m
        from db.engine import get_session_maker
        pref = await p.create(key='answer_length', value='Kurz')
        conversation, message = await setup_source()
        row, card = await candidate(conversation, message)
        assert await confirm(row, card) == 'unchanged'
        assert (await p.list_preferences())[0].version == 1
        conversation, message = await setup_source()
        row, card = await candidate(conversation, message, value='Ausführlich')
        await p.change(pref.id, 1, value='Mittellang')
        with pytest.raises(c.CandidateConflict):
            await confirm(row, card)
        assert (await m.get_message(card.id)).proposal_status == 'pending'
        async with get_session_maker()() as session:
            await p.lock(session)
            fresh = await c.get(session, row.id)
            await c.open_card(session, fresh, refresh=True)
            await session.commit()
        assert await confirm(fresh, card) == 'saved'
    asyncio.run(run())


def test_rejection_deletion_and_new_explicit_source(pg_db):
    async def run():
        from db.accessors import user_preference as p, preference_candidate as c
        from db.engine import get_session_maker
        conversation, message = await setup_source()
        row, card = await candidate(conversation, message)
        assert await confirm(row, card, 'keep') == 'kept'
        async with get_session_maker()() as session:
            rejected = await c.get(session, row.id)
            assert rejected.value is None and rejected.status == 'rejected'
        conversation2, message2 = await setup_source()
        row2, card2 = await candidate(conversation2, message2)
        await confirm(row2, card2)
        pref = (await p.list_preferences())[0]
        await p.change(pref.id, 1, delete=True)
        async with get_session_maker()() as session:
            erased = await c.get(session, row2.id)
            assert erased.value is None and erased.status == 'expired'
        with pytest.raises(c.CandidateGone):
            await candidate(conversation2, message2)
        conversation3, message3 = await setup_source()
        fresh, card3 = await candidate(conversation3, message3)
        assert await confirm(fresh, card3) == 'saved'
    asyncio.run(run())


@pytest.mark.parametrize('role', ['assistant', 'tool', 'proposal'])
def test_non_user_sources_rejected(pg_db, role):
    async def run():
        from db.accessors.preference_candidate import CandidateGone
        conversation, message = await setup_source(role)
        with pytest.raises(CandidateGone):
            await candidate(conversation, message)
    asyncio.run(run())


def test_candidate_quota_and_confirm_rechecks_preference_quota(pg_db):
    async def run():
        from db.accessors import user_preference as p
        for _ in range(50):
            conversation, message = await setup_source()
            await candidate(conversation, message)
        conversation, message = await setup_source()
        with pytest.raises(p.PreferenceConflict):
            await candidate(conversation, message)
        # Filling the stored quota after candidate creation also forbids confirmation.
        for _ in range(50):
            await p.create(key='answer_length', value='test-only', status='paused')
        from db.engine import get_session_maker
        from db.accessors import preference_candidate as c, chat_message as m
        async with get_session_maker()() as session:
            first = (await c.list_rows(session))[0]
        card = await m.get_message(first.proposal_id)
        with pytest.raises(p.PreferenceConflict):
            await confirm(first, card)
        assert (await m.get_message(card.id)).proposal_status == 'pending'
    asyncio.run(run())
