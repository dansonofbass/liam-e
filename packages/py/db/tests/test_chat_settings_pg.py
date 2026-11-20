"""Central mail grants across devices, request entry points and proposal claims."""
import asyncio
import json
import os
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from api.mail import agent, proposals, service
from api.routers.api.v1.chat import route, stream
from api.routers.api.v1.settings import chat as settings_route
from db.accessors import chat_context, chat_message, chat_settings, mail_account
from db.accessors.prompt_template import StaleVersion
from db.engine import get_session_maker
from db.models.mail_message import MailMessage

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


async def connect(name):
    return await service.upsert_account(provider='imap', auth_type='imap_password', email_address=f'{name}@example.test')


async def resolve(**kwargs):
    options = dict(conversation_id=None, title='Example', model=None, revision_id=None, account_id=None, app_prompt_version='test')
    return await chat_context.resolve(**(options | kwargs))


def test_revision_reconnect_delete_and_regrant(pg_db):
    async def run():
        a, b = await connect('one'), await connect('two')
        initial = await chat_settings.get()
        assert (initial.version, initial.account_ids) == (1, [])
        _, empty, _ = await resolve()
        assert json.loads(empty.account_scope_json)['account_ids'] == []
        edits = await asyncio.gather(chat_settings.update(1, [a.id]), chat_settings.update(1, [b.id]), return_exceptions=True)
        assert sum(isinstance(edit, StaleVersion) for edit in edits) == 1
        both = await chat_settings.update(2, [b.id, a.id])
        assert (both.version, both.account_ids) == (3, sorted([a.id, b.id]))
        assert (await chat_settings.update(3, [a.id, b.id, a.id])).version == 3
        assert (await connect('one')).id == a.id
        conversation, before, _ = await resolve(expected_mail_scope_version=3)
        await chat_message.add_message(conversation_id=conversation.id, role='assistant', context_id=before.id, content='Stored answer')
        await connect('three')
        assert await chat_context.is_live(before.id)
        assert (await chat_settings.get()).account_ids == both.account_ids
        assert await mail_account.delete_account(a.id)
        assert (await chat_settings.get()).account_ids == [b.id]
        assert not await chat_context.is_live(before.id)
        replacement = await connect('one')
        assert replacement.id != a.id
        with pytest.raises(chat_settings.AccountNotGranted):
            await resolve(account_id=replacement.id)
        with pytest.raises(StaleVersion):
            await chat_settings.update(3, [])
        with pytest.raises(chat_settings.AccountNotGranted):
            await chat_settings.update(4, [a.id])
        await chat_settings.update(4, [b.id, replacement.id])
        with pytest.raises(chat_context.ScopeChange):
            await resolve(conversation_id=conversation.id)
        assert [row.content for row in await chat_message.list_messages(conversation.id)] == ['Stored answer']
    asyncio.run(run())


def test_browser_and_compatibility_chat_reject_excluded_accounts_before_model(pg_db, monkeypatch):
    async def run():
        a, b = await connect('permitted'), await connect('excluded')
        mail = MailMessage(account_id=b.id, provider_uid='synthetic', body_text='private synthetic marker')
        granted_mail = MailMessage(account_id=a.id, provider_uid='synthetic-granted')
        async with get_session_maker()() as session:
            session.add_all([mail, granted_mail])
            await session.commit()
        model = Mock(side_effect=AssertionError('unexpected model request'))
        monkeypatch.setattr(agent, 'mistral_client', model)
        app = FastAPI()
        app.include_router(settings_route.router, prefix='/settings/chat')
        app.include_router(route.router, prefix='/chat')
        app.include_router(stream.router, prefix='/chat/stream')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/settings/chat')).json() == {'version': 1, 'account_ids': []}
            async def save(version, ids):
                return await client.patch('/settings/chat', json={'expected_version': version, 'account_ids': ids})
            assert (await save(1, [a.id])).json() == {'version': 2, 'account_ids': [a.id]}
            assert (await save(1, [])).status_code == 409
            assert (await save(2, ['missing'])).status_code == 422
            for path, field in [('/chat', 'message'), ('/chat/stream', 'text')]:
                for extra, status, code in [
                    ({'account_id': b.id}, 403, 'chat_account_not_granted'),
                    ({'context_message_id': mail.id}, 403, 'chat_account_not_granted'),
                    ({'account_id': a.id, 'context_message_id': mail.id}, 403, 'chat_account_not_granted'),
                    ({'context_message_id': 'missing'}, 403, 'chat_account_not_granted'),
                    ({'expected_mail_scope_version': 1}, 409, 'chat_settings_changed'),
                    ({'task_source': 'account', 'task_source_account_id': b.id}, 422, 'context_invalid'),
                ]:
                    response = await client.post(path, json={field: 'Question', **extra})
                    assert (response.status_code, response.json()['detail']['code']) == (status, code)
                    assert mail.body_text not in response.text
        model.assert_not_called()
        _, snapshot, _ = await resolve(context_message_id=granted_mail.id)
        assert json.loads(snapshot.account_scope_json) == {'account_ids': [a.id], 'selection': a.id}
    asyncio.run(run())


def test_confirmation_checks_grant_and_actual_sender_in_claim_transaction(pg_db, monkeypatch):
    async def run():
        a, b = await connect('allowed'), await connect('other')
        await chat_settings.update(1, [a.id])
        conversation, context, _ = await resolve()
        send = AsyncMock()
        monkeypatch.setattr(proposals.send, 'send_message', send)
        for sender in [b, a]:
            draft = proposals.SendDraft(account_id=sender.id, mode='new', to=['recipient@example.test'], cc=[],
                subject='Example', body='Example', quote='', reply_to_message_id=None)
            card = await proposals.create_proposal(conversation.id,
                proposals.Proposal(kind='send', reason='Example', items=[], draft=draft), context_id=context.id)
            if sender == a:
                await chat_settings.update(2, [])
                await chat_settings.update(3, [a.id])
            with pytest.raises(proposals.ProposalContextRevokedError):
                await proposals.confirm(card.id, selected_ids=[])
            assert (await chat_message.get_message(card.id)).proposal_status == 'pending'
            assert (await proposals.cancel(card.id)).proposal_status == 'cancelled'
        send.assert_not_awaited()
    asyncio.run(run())
