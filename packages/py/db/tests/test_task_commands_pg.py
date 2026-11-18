"""Versioned task commands through the shared proposal service."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


def test_revision_collision_keeps_card_pending_with_specific_error(pg_db):
    async def run():
        from fastapi import HTTPException
        from api.mail import proposals
        from api.tasks import state
        from api.tasks.proposals import TaskCreateCommand, TaskPatchCommand
        from db.accessors import chat_message, task_occurrence, task_series
        from db.engine import get_session_maker
        from db.models.chat_context import ChatContext
        start = datetime.now(UTC).date() + timedelta(days=7)
        async with get_session_maker()() as session:
            context = ChatContext(conversation_id='synthetic', app_prompt_version='test-only',
                account_scope_json='{"selection":null}', task_scope_json='{"source":"all"}')
            session.add(context)
            await session.commit()
        async def propose(command):
            return await proposals.create_proposal('synthetic', proposals.Proposal(kind='task', reason='Example',
                items=[], task=command), context_id=context.id)
        initial = await propose(TaskCreateCommand(action='create', title='Example', start=start.isoformat(),
            timezone='UTC', rrule='FREQ=DAILY;COUNT=3'))
        done = await proposals.confirm(initial.id, selected_ids=[])
        series_id = proposals.proposal_view(done).result.task_series_id
        async with get_session_maker()() as session:
            rows = await task_occurrence.list_page(session, scope='app', status=None, due_from=None, due_to=None,
                after=None, limit=10, series_id=series_id)
            await state.transition(session, rows[1].id, version=rows[1].version, action='complete')
            await session.commit()
        card = await propose(TaskPatchCommand(action='patch', series_id=series_id, expected_version=1,
            occurrence_id=rows[0].id, expected_occurrence_version=rows[0].version,
            scope='this_and_following', start=rows[1].due_local, timezone='UTC'))
        with pytest.raises(HTTPException) as caught:
            await proposals.confirm(card.id, selected_ids=[])
        assert caught.value.status_code == 409
        assert caught.value.detail == {'code': 'task_revision_conflict', 'message':
            'Die neue Wiederholung überschneidet sich mit einer erledigten Fälligkeit. Wähle einen anderen Zeitplan.'}
        assert (await chat_message.get_message(card.id)).proposal_status == 'pending'
        async with get_session_maker()() as session:
            assert (await task_series.get(session, 'app', series_id)).version == 1
            assert (await task_occurrence.get(session, rows[0].id)).status == 'open'
    asyncio.run(run())


@pytest.mark.parametrize('action', ['patch', 'split', 'complete', 'skip', 'reopen', 'archive'])
@pytest.mark.parametrize('conflict', [False, True])
def test_bound_commands_execute_once(pg_db, action, conflict):
    async def run():
        from api.mail import proposals
        from api.tasks.proposals import TaskArchiveCommand, TaskCreateCommand, TaskPatchCommand, TaskStateCommand
        from api.tasks import state
        from db.accessors import task_occurrence, task_series
        from db.engine import get_session_maker
        from db.models.chat_context import ChatContext

        async with get_session_maker()() as session:
            context = ChatContext(conversation_id='synthetic', app_prompt_version='test-only',
                account_scope_json='{"selection":null}', task_scope_json='{"source":"all"}')
            session.add(context)
            await session.commit()
        async def propose(command):
            return await proposals.create_proposal('synthetic', proposals.Proposal(kind='task', reason='Example',
                items=[], task=command), context_id=context.id)
        today = datetime.now(UTC).date()
        initial = await propose(TaskCreateCommand(action='create', title='Example', start=(today + timedelta(days=7)).isoformat(), timezone='UTC'))
        done = await proposals.confirm(initial.id, selected_ids=[])
        series_id = proposals.proposal_view(done).result.task_series_id
        async with get_session_maker()() as session:
            rows = await task_occurrence.list_page(session, scope='app', status=None, due_from=None, due_to=None,
                                                   after=None, limit=10, series_id=series_id)
            occurrence = rows[0]
            if action == 'reopen':
                occurrence = await state.transition(session, occurrence.id, version=occurrence.version, action='complete')
                await session.commit()
        common = dict(series_id=series_id, expected_version=1)
        target = dict(occurrence_id=occurrence.id, expected_occurrence_version=occurrence.version)
        if action == 'archive':
            command = TaskArchiveCommand(action=action, **common)
        elif action in {'patch', 'split'}:
            command = TaskPatchCommand(action='patch', **common, **target,
                scope='occurrence' if action == 'patch' else 'this_and_following',
                timezone='UTC' if action == 'split' else None,
                start=(today + timedelta(days=8)).isoformat())
        else:
            command = TaskStateCommand(action=action, **common, **target)
        message = await propose(command)
        async with get_session_maker()() as session:
            before = await task_occurrence.get(session, occurrence.id)
            assert before.version == occurrence.version
        if conflict:
            from api.tasks import lifecycle
            from fastapi import HTTPException
            from db.accessors import chat_message
            async with get_session_maker()() as session:
                await lifecycle.archive(session, series_id, expected_version=1)
                await session.commit()
            with pytest.raises(HTTPException) as caught:
                await proposals.confirm(message.id, selected_ids=[])
            assert caught.value.status_code == 409
            assert caught.value.detail['code'] == 'task_version_conflict'
            assert (await chat_message.get_message(message.id)).proposal_status == 'pending'
            async with get_session_maker()() as session:
                row = await task_series.get(session, 'app', series_id)
                assert row.version == 2
            return
        assert (await proposals.confirm(message.id, selected_ids=[])).proposal_status == 'done'
        with pytest.raises(proposals.ProposalStateError):
            await proposals.confirm(message.id, selected_ids=[])
        async with get_session_maker()() as session:
            row = await task_series.get(session, 'app', series_id)
            after = await task_occurrence.get(session, occurrence.id)
            if action == 'archive':
                assert row.archived
            elif action == 'split':
                assert after is None and row.version == 2
                rows = await task_occurrence.list_page(session, scope='app', status='open', due_from=None,
                    due_to=None, after=None, limit=10, series_id=series_id)
                assert [item.due_local for item in rows] == [command.start]
            elif action == 'patch':
                assert after.due_local == command.start and row.version == 2
            else:
                assert after.status == {'complete': 'completed', 'skip': 'skipped', 'reopen': 'open'}[action]
                assert after.version == occurrence.version + 1
    asyncio.run(run())
