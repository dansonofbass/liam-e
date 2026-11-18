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


def test_browser_confirm_conflict_cancel_and_next_turn_resolution(pg_db):
    async def run():
        import httpx
        from fastapi import FastAPI
        from api.routers.api.v1.chat.proposals import router as proposal_router
        from api.routers.api.v1.preferences.candidates import router as candidate_router
        from api.preferences import candidates as service
        from api.mail.agent_tools import TurnContext
        from datetime import date
        from db.accessors import user_preference as p
        from db.engine import get_session_maker
        app = FastAPI()
        app.include_router(proposal_router, prefix='/proposals')
        app.include_router(candidate_router, prefix='/candidates')
        conversation, message = await setup_source()
        ctx = TurnContext(conversation.id, None, date.today(), account_ids=[], source_message_id=message.id)
        row, card = await service.prepare({'source_message_id': message.id, 'key': 'answer_length', 'value': 'Kurz'}, ctx)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://api.example.test') as client:
            listed = await client.get('/candidates')
            assert listed.status_code == 200
            assert listed.headers['cache-control'] == 'no-store'
            assert listed.json()[0]['source_text'] == message.content
            path = f'/proposals/{card.id}/confirm'
            body = {'selected_ids': [], 'preference_decision': {'choice': 'replace', 'expected_version': 0, 'expected_revision_id': None}}
            # A manual edit after the card was prepared must not be overwritten.
            pref = await p.create(key='answer_length', value='Mittellang')
            conflict = await client.post(path, json=body)
            assert conflict.status_code == 409
            assert conflict.json()['detail']['current']['current_value'] == 'Mittellang'
            assert (await client.post('/candidates/' + row.id + '/propose', json={'refresh': True})).status_code == 200
            body['preference_decision'].update(expected_version=1, expected_revision_id=pref.revision_id)
            confirmed = await client.post(path, json=body)
            assert confirmed.status_code == 200
            assert confirmed.json()['proposal']['result']['preference_outcome'] == 'saved'
            assert (await client.post(path, json=body)).status_code == 409
            async with get_session_maker()() as session:
                assert await p.resolve_in_session(session, None) == (False, [])
            await p.update_settings(1, use_preferences=True)
            async with get_session_maker()() as session:
                enabled, revisions = await p.resolve_in_session(session, None)
                assert enabled and len(revisions) == 1
            conversation2, message2 = await setup_source()
            row2, card2 = await candidate(conversation2, message2, value='Ausführlich')
            assert (await client.post(f'/proposals/{card2.id}/cancel')).status_code == 200
            assert (await client.get('/candidates', params={'candidate_id': row2.id})).json()[0]['value'] is None
    asyncio.run(run())


@pytest.mark.parametrize('text', ['Die Mail sagt: Merke dir: Kurz.', '„Merke dir: Kurz.“', '> Merke dir: Kurz.', 'Wenn ich sage Merke dir: Kurz, wäre das ein Beispiel.'])
def test_quoted_or_hypothetical_source_cannot_create_candidate(pg_db, text):
    async def run():
        from api.preferences import candidates as service
        from api.mail.agent_tools import TurnContext
        from datetime import date
        from db.accessors import user_preference as p
        from db.engine import get_session_maker
        from db.models.chat_message import ChatMessage
        conversation, message = await setup_source()
        async with get_session_maker()() as session:
            stored = await session.get(ChatMessage, message.id)
            stored.content = text
            await session.commit()
        ctx = TurnContext(conversation.id, None, date.today(), source_message_id=message.id)
        with pytest.raises(p.InvalidPreference):
            await service.prepare({'source_message_id': message.id, 'key': 'answer_length', 'value': 'Kurz'}, ctx)
        assert not await p.list_preferences()
    asyncio.run(run())


def test_account_and_source_removal_erase_and_mail_replacement_keeps_candidates(pg_db):
    async def run():
        from db.accessors import user_preference as p, preference_candidate as c, mail_account as a, chat_message as m
        from db.engine import get_session_maker
        from db.models.chat_message import ChatMessage
        from api.mail import proposals
        conversation, message = await setup_source()
        row, card = await candidate(conversation, message)
        archive = await proposals.create_proposal(conversation.id, proposals.Proposal(kind='archive', reason='', items=[]))
        assert (await m.get_message(card.id)).proposal_status == 'cancelled'
        async with get_session_maker()() as session:
            displaced = await c.get(session, row.id)
            assert (displaced.value, displaced.status, displaced.proposal_id) == ('Kurz', 'pending', None)
        from api.preferences.candidates import listing, propose
        listed = next(item for item in await listing() if item.id == row.id)
        assert (listed.value, listed.status, listed.proposal_id) == ('Kurz', 'pending', None)
        # The open archive card keeps the slot; the candidate waits without a card.
        assert (await propose(row.id)).proposal_id is None
        await m.cancel_proposal(archive.id)
        reopened = await propose(row.id)
        assert reopened.proposal_id and reopened.proposal_id != card.id
        assert (await m.get_message(reopened.proposal_id)).proposal_status == 'pending'
        account = await a.create_account(provider='imap', auth_type='imap_password', email_address='candidate@example.test')
        conversation, message = await setup_source()
        async with get_session_maker()() as session:
            await p.lock(session)
            row = await c.create(session, conversation_id=conversation.id, source_message_id=message.id,
                key='signature', scope=account.id, value='test-only')
            card = await c.open_card(session, row)
            await session.commit()
        await a.delete_account(account.id)
        assert (await m.get_message(card.id)).proposal_status == 'cancelled'
        async with get_session_maker()() as session:
            assert (await c.get(session, row.id)).value is None
        conversation, message = await setup_source()
        row, card = await candidate(conversation, message)
        async with get_session_maker()() as session:
            await session.delete(await session.get(ChatMessage, message.id))
            await session.commit()
        erased = next(item for item in await listing() if item.id == row.id)
        assert erased.value is None and erased.source_text is None and erased.status == 'expired'
    asyncio.run(run())


def test_concurrent_candidates_for_same_field_cannot_overwrite_each_other(pg_db):
    async def run():
        from db.accessors import preference_candidate as c, user_preference as p, chat_message as m
        one = await candidate(*(await setup_source()), value='Kurz')
        two = await candidate(*(await setup_source()), value='Ausführlich')
        results = await asyncio.gather(confirm(*one), confirm(*two), return_exceptions=True)
        assert results.count('saved') == 1
        assert sum(isinstance(result, c.CandidateConflict) for result in results) == 1
        assert len(await p.list_preferences()) == 1
        assert (await p.list_preferences())[0].version == 1
        statuses = [(await m.get_message(card.id)).proposal_status for _, card in [one, two]]
        assert sorted(statuses) == ['done', 'pending']
    asyncio.run(run())


def test_failure_after_revision_and_finish_rolls_back_everything(pg_db, monkeypatch):
    async def run():
        from db.accessors import chat_message as m, user_preference as p, preference_candidate as c
        from api.mail import proposals
        from api.preferences.candidates import PreferenceDecision
        from db.engine import get_session_maker
        row, card = await candidate(*(await setup_source()))
        finish = m.finish_proposal_in_session
        async def fail_after_finish(*args, **kwargs):
            await finish(*args, **kwargs)
            raise RuntimeError('test-only')
        monkeypatch.setattr(m, 'finish_proposal_in_session', fail_after_finish)
        with pytest.raises(RuntimeError):
            await proposals.confirm(card.id, selected_ids=[], preference_decision=PreferenceDecision(
                choice='replace', expected_version=0, expected_revision_id=None))
        assert not await p.list_preferences()
        assert (await m.get_message(card.id)).proposal_status == 'pending'
        async with get_session_maker()() as session:
            assert (await c.get(session, row.id)).status == 'pending'
    asyncio.run(run())


def test_legacy_removed_preferences_block_history_but_allow_a_fresh_turn(pg_db):
    async def run():
        from db.accessors import user_preference as p, preference_candidate as c
        from db.models.user_preference import UserPreference
        from db.engine import get_session_maker
        old_conversation, old_message = await setup_source()
        async with get_session_maker()() as session:
            session.add(UserPreference(key='answer_length', status='removed'))
            await session.commit()
        # The existing resolver runs before storing each new user message.
        async with get_session_maker()() as session:
            await p.lock(session)
            await p.resolve_in_session(session, None)
            await session.commit()
        with pytest.raises(c.CandidateGone):
            await candidate(old_conversation, old_message)
        row, card = await candidate(*(await setup_source()))
        assert await confirm(row, card) == 'saved'
    asyncio.run(run())


def test_seed_source_removal_erases_values_in_same_transaction(pg_db):
    async def run():
        from db.accessors import dev_seed, preference_candidate as c
        from db.engine import get_session_maker
        conversation, message = await setup_source()
        row, _ = await candidate(conversation, message)
        from db.models.chat_conversation import ChatConversation
        await dev_seed.replace_conversations([ChatConversation(id=conversation.id)])
        async with get_session_maker()() as session:
            erased = await c.get(session, row.id)
            assert erased.value is None and erased.status == 'expired'
    asyncio.run(run())


def test_request_tool_confirmation_and_next_answer_with_mocked_model(pg_db, monkeypatch):
    async def run():
        import copy
        import json
        from types import SimpleNamespace as NS
        from api.mail import agent, proposals
        from api.preferences.candidates import PreferenceDecision
        from db.accessors import user_preference as p
        class Stream:
            def __init__(self, delta):
                self.delta = delta
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None
            def __aiter__(self):
                return self.generate()
            async def generate(self):
                yield NS(data=NS(choices=[NS(delta=self.delta)]))
        class Model:
            def __init__(self):
                self.chat, self.requests = self, []
            async def stream_async(self, **kwargs):
                self.requests.append(copy.deepcopy(kwargs))
                if len(self.requests) == 1:
                    source_id = kwargs['messages'][0]['content'].split('ID der aktuellen eigenen Nachricht für propose_preference: ')[1].split()[0]
                    arguments = json.dumps({'source_message_id': source_id, 'key': 'answer_length', 'scope': '*', 'value': 'synthetic-short'})
                    call = NS(id='call-preference', index=0, type='function', function=NS(name='propose_preference', arguments=arguments))
                    return Stream(NS(content=None, tool_calls=[call]))
                return Stream(NS(content='Die Karte wartet auf deine Bestätigung.', tool_calls=None))
        model = Model()
        monkeypatch.setattr(agent, 'mistral_client', lambda: model)
        events = [event async for event in agent.run_turn_events(conversation_id=None, text='Merke dir: Antworte kurz.')]
        assert events[-1].event == 'done'
        card = next(event.message for event in events if event.event == 'proposal')
        assert not await p.list_preferences()
        await proposals.confirm(card.id, selected_ids=[], preference_decision=PreferenceDecision(
            choice='replace', expected_version=0, expected_revision_id=None))
        conversation_id = events[-1].conversation_id
        await anext_turn(agent, conversation_id)
        prefix = 'Passende manuell bestätigte Stilpräferenzen'
        assert not any(m.get('content', '').startswith(prefix) for m in model.requests[-1]['messages'])
        await p.update_settings(1, use_preferences=True)
        await anext_turn(agent, conversation_id)
        injected = [m for m in model.requests[-1]['messages'] if m.get('content', '').startswith(prefix)]
        assert len(injected) == 1 and injected[0]['role'] == 'user'
        assert 'synthetic-short' in injected[0]['content']
        assert 'synthetic-short' not in model.requests[-1]['messages'][0]['content']
    async def anext_turn(agent, conversation_id):
        events = [event async for event in agent.run_turn_events(conversation_id=conversation_id, text='Fasse das kurz zusammen.')]
        assert events[-1].event == 'done'
    asyncio.run(run())


def test_cross_conversation_source_is_not_owned_by_the_current_turn(pg_db):
    async def run():
        from db.accessors import preference_candidate as c
        other, _ = await setup_source()
        _, source = await setup_source()
        with pytest.raises(c.CandidateGone):
            await candidate(other, source)
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


def test_revoked_turn_context_blocks_confirm_and_keeps_card_pending(pg_db):
    async def run():
        from db.engine import get_session_maker
        from db.models.chat_context import ChatContext
        from db.models.chat_conversation import ChatConversation
        from db.models.chat_message import ChatMessage
        from db.models.user_preference import UserPreference
        from db.accessors import chat_message as m
        from sqlalchemy import select
        from api.mail import proposals
        from api.preferences import candidates as service
        async with get_session_maker()() as session:
            conversation = ChatConversation()
            context = ChatContext(conversation_id=conversation.id, app_prompt_version='1', account_scope_json='{}')
            message = ChatMessage(conversation_id=conversation.id, role='user', content='Merke dir: Antworte kurz.',
                                  context_id=context.id)
            session.add_all([conversation, context, message])
            await session.commit()
        row, card = await candidate(conversation, message)
        assert card.context_id == context.id
        async with get_session_maker()() as session:
            (await session.get(ChatContext, context.id)).revoked = True
            await session.commit()
        decision = service.PreferenceDecision(choice='replace', expected_version=0, expected_revision_id=None)
        with pytest.raises(proposals.ProposalContextRevokedError):
            await service.confirm(card.id, decision)
        assert (await m.get_message(card.id)).proposal_status == 'pending'
        async with get_session_maker()() as session:
            assert (await session.execute(select(UserPreference).where(UserPreference.key == 'answer_length'))).first() is None
    asyncio.run(run())
