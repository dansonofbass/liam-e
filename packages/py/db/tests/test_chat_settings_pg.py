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


def test_live_preview_only_exposes_authorized_short_references(pg_db):
    from api.routers.api.v1.chat import references
    async def run():
        first, second = await connect('first'), await connect('second')
        await chat_settings.update(1, [first.id, second.id])
        _, focus, _ = await resolve(account_id=first.id)
        rows = [MailMessage(account_id=a.id, provider_uid='one', subject='Synthetic', snippet='Short', body_text='Full private text') for a in (first, second)]
        async with get_session_maker()() as session:
            session.add_all(rows)
            await session.commit()
        app = FastAPI()
        app.include_router(references.router, prefix='/refs')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            async def preview(id, version=2, context=None):
                params = {'expected_version': version}
                if context:
                    params['context_id'] = context
                return await client.get('/refs/' + id, params=params)
            allowed = await preview(rows[0].id, context=focus.id)
            assert allowed.status_code == 200 and allowed.json()['snippet'] == 'Short'
            assert 'body_text' not in allowed.json() and 'Full private text' not in allowed.text
            assert (await preview(rows[1].id)).status_code == 200
            assert (await preview(rows[1].id, context=focus.id)).json() == (await preview('missing')).json()
            await chat_settings.update(2, [second.id])
            for id, version, context in [(rows[0].id, 2, None), (rows[0].id, 3, None), (rows[1].id, 3, focus.id)]:
                assert (await preview(id, version, context)).status_code == 404
            assert (await preview(rows[1].id, 3)).status_code == 200
    asyncio.run(run())


def test_connector_indexes_need_positive_verification_and_explicit_regrant(pg_db):
    from db.accessors import mail_sync_state
    from api.mail import connector_mailbox, connectors
    async def run():
        a = await service.upsert_account(provider='gmail', auth_type=connectors.CONNECTOR, email_address='a@example.test')
        async def save(cursor, checked):
            await mail_sync_state.save_state(account_id=a.id, cursor="234", connector_cursor=cursor, connector_verified=checked)
        await save('234', False)
        with pytest.raises(chat_settings.AccountNotGranted):
            await chat_settings.update(1, [a.id])
        legacy = MailMessage(account_id=a.id, provider_uid='legacy', folder='ARCHIVE', unverified_connector=True)
        async with get_session_maker()() as session:
            session.add(legacy)
            await session.commit()
        cursor = connector_mailbox.encode(('named', 'thread', 'message'), '244')
        await save(cursor, True)
        await chat_settings.update(1, [a.id])
        _, original, _ = await resolve(account_id=a.id)
        assert await chat_context.is_live(original.id)
        with pytest.raises(chat_settings.AccountNotGranted):
            await resolve(context_message_id=legacy.id)
        assert await chat_settings.mail_preview(legacy.id, 2, original.id) is None
        await chat_settings.invalidate_connector(a.id)
        assert not await chat_context.is_live(original.id)
        with pytest.raises(chat_settings.AccountNotGranted):
            await chat_settings.update(3, [a.id])
        await save(cursor, True)
        assert (await chat_settings.get()).account_ids == []
        assert (await chat_settings.update(3, [a.id])).version == 4
        assert not await chat_context.is_live(original.id)
    asyncio.run(run())


def test_connector_upgrade_verifies_pages_in_place_and_keeps_ordinary_inbox_only_accounts(pg_db, monkeypatch):
    from db.accessors import mail_message, mail_sync_state
    from api.mail import connector_mailbox, connectors, sync
    from api.mail.sync_types import BODY_VERSION

    async def run():
        a = await service.upsert_account(provider='gmail', auth_type=connectors.CONNECTOR, email_address='a@example.test')
        placeholder = await service.upsert_account(provider='gmail', auth_type=connectors.CONNECTOR, email_address='gmail@connector.mistral')
        legacy = [await mail_message.upsert_message(account_id=a.id, folder='INBOX', provider_uid=uid,
            subject='Previous', unverified_connector=True, body_version=BODY_VERSION) for uid in ('one', 'two', 'absent')]
        from db.models.mail_insight import MailInsight
        async with get_session_maker()() as session:
            session.add(MailInsight(message_id=legacy[0].id, needs_reply=True, model="fixture"))
            await session.commit()
        await mail_sync_state.save_state(account_id=a.id, cursor='234')
        listing = AsyncMock(side_effect=[{'credentials': None}, {'credentials': [{'name': 'identity', 'authentication_type': 'oauth2'}]}])
        monkeypatch.setattr(connectors, '_get', listing)
        monkeypatch.setattr(sync.mail_env, 'mail_sync_page_size', 1)
        pages = []
        async def provider(name, tool, args):
            anchor = {'id': 'sent', 'messages': [{'id': 'sent-proof', 'labelIds': ['SENT'], 'sender': a.email_address}]}
            if args.get('query') == 'in:sent from:me':
                return {'threads': [anchor]}
            if args.get('threadId') == 'sent':
                return anchor
            if tool == 'search_threads':
                if 'after:' in args['query']:
                    return {'threads': [{'id': 'new-arrival'}]}
                if 'newer_than:' in args['query']:
                    return {'threads': []}
                assert args['query'] == 'in:inbox'
                pages.append(args.get('pageToken'))
                if args.get('pageToken'):
                    return {'threads': [{'id': 'two'}]}
                return {'threads': [{'id': 'one'}], 'nextPageToken': 'opaque-next'}
            uid = args['threadId']
            return {'id': uid, 'messages': [{'id': uid, 'labelIds': ['INBOX', 'UNREAD'], 'date': '2026-01-01T10:00:00+00:00', 'subject': 'Checked'}]}
        monkeypatch.setattr(connectors, 'call_read_tool_json', provider)
        first = await sync.sync_account(a.id)
        assert first.status == 'ok' and first.new_message_ids == [] and first.refresh_insights
        assert listing.await_args_list[1].args[0].endswith('/user/credentials')
        assert connector_mailbox.decode(first.cursor)[1].startswith('initial:')
        assert not (await mail_message.get_message(legacy[0].id)).unverified_connector
        assert (await mail_message.get_message(legacy[1].id)).unverified_connector
        assert (await sync.sync_account(a.id)).status == 'ok' and pages == [None, 'opaque-next']
        arrivals = await mail_message.list_page(account_ids=[a.id], chat_only=True)
        assert 'new-arrival' in {m.provider_uid for m in arrivals}
        assert not (await mail_message.get_message(legacy[1].id)).unverified_connector
        assert (await mail_message.get_message(legacy[2].id)).folder == 'INBOX'
        await chat_settings.update(1, [a.id])
        assert await chat_settings.mail_preview(legacy[2].id, 2, None) is None
        assert (await sync.sync_account(placeholder.id)).status == 'ok'
        rows = await mail_message.list_page(account_ids=[placeholder.id])
        assert len(rows) == 1 and rows[0].unverified_connector
        assert not (await mail_sync_state.get_state(placeholder.id)).connector_verified
        with pytest.raises(chat_settings.AccountNotGranted):
            await chat_settings.update(2, [placeholder.id])
    asyncio.run(run())


def test_unverified_task_mail_is_refused_at_proposal_and_confirmation(pg_db):
    from types import SimpleNamespace
    from api.tasks import chat, proposals as task_proposals
    from db.accessors import mail_message
    async def run():
        a = await connect('source')
        row = await mail_message.upsert_message(account_id=a.id, folder='ARCHIVE', provider_uid='old', unverified_connector=True)
        ctx = SimpleNamespace(task_scope={'source': 'all'}, account_ids=[a.id], account_id=None, source_message_id=None)
        request = dict(action='create', title='Example', start='2027-01-01', timezone='UTC', source_message_id=row.id)
        with pytest.raises(ValueError, match='task_scope_invalid'):
            await chat.prepare(request, ctx)
        command = task_proposals.TaskCreateCommand(**request, source_account_id=a.id)
        async with get_session_maker()() as session:
            with pytest.raises(task_proposals.TaskSourceGone):
                await task_proposals.execute(session, command, proposal_id='unverified')
    asyncio.run(run())


def test_legacy_writes_and_obsolete_batches_cannot_publish_verified_mail(pg_db):
    from db.accessors import mail_message, mail_sync_state
    from api.mail import connector_mailbox, connectors
    async def run():
        a = await service.upsert_account(provider='gmail', auth_type=connectors.CONNECTOR, email_address='rollout@example.test')
        initial = await mail_sync_state.save_state(account_id=a.id, cursor='12')
        async with mail_sync_state.connector_transaction(a.id, initial, verified=True) as (session, state):
            verified = await mail_message.upsert_message(session=session, account_id=a.id, folder='INBOX', provider_uid='one', subject='Verified')
            state.connector_cursor = connector_mailbox.encode(('named', 'thread', 'proof'), '12')
            state.connector_verified = True
        await chat_settings.update(1, [a.id])
        assert await chat_settings.mail_preview(verified.id, 2, None) is not None
        # Both a new insert and an update by a transaction without a verified provider read are quarantined.
        old = await mail_message.upsert_message(account_id=a.id, folder='INBOX', provider_uid='legacy', subject='Legacy')
        await mail_message.upsert_message(account_id=a.id, folder='INBOX', provider_uid='one', subject='Legacy overwrite')
        old_state = await mail_sync_state.save_state(account_id=a.id, cursor='17')
        assert old_state.connector_cursor and old_state.cursor == '17'
        for row in (old, verified):
            assert await chat_settings.mail_preview(row.id, 2, None) is None
        await chat_settings.invalidate_connector(a.id, old_state.connector_generation)
        with pytest.raises(mail_sync_state.StaleConnectorSync):
            async with mail_sync_state.connector_transaction(a.id, old_state, verified=True):
                pytest.fail('stale publication was admitted')
        with pytest.raises(chat_settings.AccountNotGranted):
            await chat_settings.update(3, [a.id])
        current = await mail_sync_state.get_state(a.id)
        with pytest.raises(RuntimeError, match='incomplete page'):
            async with mail_sync_state.connector_transaction(a.id, current, verified=True) as (session, state):
                await mail_message.upsert_message(session=session, account_id=a.id, folder='INBOX', provider_uid='partial')
                state.connector_verified = True
                raise RuntimeError('incomplete page')
        assert 'partial' not in await mail_message.known_uids(a.id, 'INBOX')
        assert not (await mail_sync_state.get_state(a.id)).connector_verified
    asyncio.run(run())
