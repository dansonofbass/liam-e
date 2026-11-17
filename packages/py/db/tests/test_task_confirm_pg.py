"""Task effects and proposal completion share a real PostgreSQL transaction."""

import asyncio
import json
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


async def proposal(*, source='all', revoked=False):
    from db.engine import get_session_maker
    from db.models.chat_context import ChatContext
    from api.mail.proposals import Proposal, create_proposal
    from api.tasks.proposals import TaskCreateCommand

    async with get_session_maker()() as session:
        context = ChatContext(conversation_id='synthetic', app_prompt_version='test-only',
            account_scope_json='{"selection":null,"account_ids":[]}',
            task_scope_json=json.dumps({'source': source}), revoked=revoked)
        session.add(context)
        await session.commit()
    return await create_proposal('synthetic', Proposal(kind='task', reason='Example', items=[],
        task=TaskCreateCommand(action='create', title='Example', start=date.today().isoformat(), timezone='UTC')),
        context_id=context.id)


def test_mail_and_task_cards_share_one_pending_slot_and_cancel_has_no_effect(pg_db):
    async def run():
        from api.mail import proposals
        from db.accessors import chat_message, task_series
        from db.engine import get_session_maker
        first = await proposal()
        mail = await proposals.create_proposal('synthetic', proposals.Proposal(kind='archive', reason='Example',
            items=[proposals.ProposalItem(id='synthetic-mail', kind='mail', title='Example', subtitle='')]))
        assert (await chat_message.get_message(first.id)).proposal_status == 'cancelled'
        last = await proposal()
        assert (await chat_message.get_message(mail.id)).proposal_status == 'cancelled'
        assert (await chat_message.open_proposal('synthetic')).id == last.id
        await proposals.cancel(last.id)
        async with get_session_maker()() as session:
            rows = await task_series.list_page(session, scope='app', due_from='2000-01-01', due_to='2100-01-01',
                archived=None, source='all', source_account_id=None, after=None, limit=10)
            assert rows == []
    asyncio.run(run())


def test_create_edit_is_bound_and_stored_with_the_actual_result(pg_db):
    async def run():
        from api.mail import proposals
        from api.tasks.proposals import TaskCreateCommand
        from db.accessors import task_series, task_schedule_revision, chat_message
        from db.engine import get_session_maker
        message = await proposal()
        with pytest.raises(proposals.ProposalSelectionError):
            await proposals.confirm(message.id, selected_ids=[], task_edit=TaskCreateCommand(
                action='create', title='Other source', start=date.today().isoformat(), timezone='UTC',
                source_account_id='foreign', source_message_id='foreign'))
        assert (await chat_message.get_message(message.id)).proposal_status == 'pending'
        edit = TaskCreateCommand(action='create', title='Edited example', start=date.today().isoformat(),
                                 timezone='UTC', rrule='FREQ=DAILY;COUNT=2')
        done = await proposals.confirm(message.id, selected_ids=[], task_edit=edit)
        saved = proposals.proposal_view(done)
        assert saved.task == edit
        async with get_session_maker()() as session:
            row = await task_series.get(session, 'app', saved.result.task_series_id)
            schedule = await task_schedule_revision.current(session, row.id)
            assert row.title == edit.title and row.description == ''
            assert schedule.rrule == edit.rrule and schedule.timezone == edit.timezone
    asyncio.run(run())


def test_deleted_source_is_not_replaced_and_can_still_be_cancelled(pg_db):
    async def run():
        from api.mail import proposals
        from api.tasks.proposals import TaskCreateCommand
        from db.accessors import chat_message
        from db.engine import get_session_maker
        from db.models.mail_account import MailAccount
        from db.models.mail_message import MailMessage
        from fastapi import HTTPException
        initial = await proposal()
        account = MailAccount(provider='imap', auth_type='imap_password', email_address='person@example.org')
        mail = MailMessage(account_id=account.id, provider_uid='synthetic')
        async with get_session_maker()() as session:
            session.add(account)
            session.add(mail)
            await session.commit()
        message = await proposals.create_proposal('synthetic', proposals.Proposal(kind='task', reason='Example', items=[],
            task=TaskCreateCommand(action='create', title='Example', start=date.today().isoformat(), timezone='UTC',
                source_account_id=account.id, source_message_id=mail.id)), context_id=initial.context_id)
        async with get_session_maker()() as session:
            row = await session.get(MailMessage, mail.id)
            await session.delete(row)
            await session.commit()
        with pytest.raises(HTTPException) as caught:
            await proposals.confirm(message.id, selected_ids=[])
        assert caught.value.status_code == 409 and caught.value.detail['code'] == 'task_source_gone'
        assert (await chat_message.get_message(message.id)).proposal_status == 'pending'
        assert (await proposals.cancel(message.id)).proposal_status == 'cancelled'
    asyncio.run(run())


def test_parallel_http_confirm_and_lost_response_retry(pg_db):
    async def run():
        import httpx
        from fastapi import FastAPI
        from api.routers.api.v1.chat.proposals import router
        from db.accessors import task_series
        from db.engine import get_session_maker

        message = await proposal()
        app = FastAPI()
        app.include_router(router, prefix='/proposals')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            async def confirm():
                return await client.post(f'/proposals/{message.id}/confirm', json={'selected_ids': []})
            results = await asyncio.gather(confirm(), confirm())
            assert sorted(r.status_code for r in results) == [200, 409]
            result = next(r.json() for r in results if r.status_code == 200)
            series_id = result['proposal']['result']['task_series_id']
            assert (await confirm()).status_code == 409
        async with get_session_maker()() as session:
            row = await task_series.get(session, 'app', series_id)
            assert row is not None and row.creation_key == message.id
            rows = await task_series.list_page(session, scope='app', due_from='2000-01-01', due_to='2100-01-01',
                archived=None, source='all', source_account_id=None, after=None, limit=10)
            assert len(rows) == 1
    asyncio.run(run())


@pytest.mark.parametrize('point', ['mutation', 'finish'])
def test_confirm_failure_rolls_back_everything(pg_db, monkeypatch, point):
    async def run():
        from api.mail import proposals
        from api.tasks import create
        from db.accessors import chat_message
        from db.engine import get_session_maker

        message = await proposal()
        owner, name = ((proposals.task_proposals, 'execute') if point == 'mutation'
                       else (chat_message, 'finish_proposal_in_session'))
        original = getattr(owner, name)
        async def interrupt(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError('test-only interruption')
        monkeypatch.setattr(owner, name, interrupt)
        with pytest.raises(RuntimeError, match='test-only interruption'):
            await proposals.confirm(message.id, selected_ids=[])
        assert (await chat_message.get_message(message.id)).proposal_status == 'pending'
        async with get_session_maker()() as session:
            _, created = await create.create(session, creation_key=message.id, title='Rollback probe',
                                             start=date.today(), zone='UTC')
            assert created
            await session.rollback()
        monkeypatch.setattr(owner, name, original)
        assert (await proposals.confirm(message.id, selected_ids=[])).proposal_status == 'done'
    asyncio.run(run())


@pytest.mark.parametrize('source,revoked,code', [('none', False, 'task_scope_invalid'), ('all', True, 'proposal_context_revoked')])
def test_confirm_denies_missing_scope_and_revocation(pg_db, source, revoked, code):
    async def run():
        import httpx
        from fastapi import FastAPI
        from api.routers.api.v1.chat.proposals import router
        from db.accessors import chat_message
        message = await proposal(source=source, revoked=revoked)
        app = FastAPI()
        app.include_router(router, prefix='/proposals')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post(f'/proposals/{message.id}/confirm', json={'selected_ids': []})
            assert response.status_code in {403, 409}
            assert response.json()['detail']['code'] == code
        assert (await chat_message.get_message(message.id)).proposal_status == 'pending'
    asyncio.run(run())
