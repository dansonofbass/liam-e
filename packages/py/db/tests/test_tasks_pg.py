"""Live Postgres uniqueness and retry contracts for task rows."""

import asyncio
import os
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.skipif(not os.getenv('RUN_PG_CONTRACT'), reason='RUN_PG_CONTRACT is not set')


def test_creation_and_occurrence_retries_are_idempotent(pg_db):
    async def run():
        from db.accessors import task_occurrence, task_series
        from db.engine import get_session_maker
        from db.models.task_occurrence import TaskOccurrence
        from db.models.task_series import TaskSeries

        async with get_session_maker()() as session:
            first, created = await task_series.create_once(session, TaskSeries(scope='app', creation_key='request-1', creation_hash='hash-1', title='Example'))
            assert created
            original_id = first.id
            await session.commit()
        async with get_session_maker()() as session:
            duplicate, created = await task_series.create_once(session, TaskSeries(scope='app', creation_key='request-1', creation_hash='hash-2', title='Other'))
            assert not created and duplicate.id == original_id and duplicate.creation_hash == 'hash-1'
            row = TaskOccurrence(series_id=original_id, revision_id='revision-1', occurrence_key='2024-01-01', due_local='2024-01-01')
            assert await task_occurrence.insert_once(session, row)
            await session.commit()
        async with get_session_maker()() as session:
            retry = TaskOccurrence(series_id=original_id, revision_id='revision-1', occurrence_key='2024-01-01', due_local='2024-01-01')
            assert not await task_occurrence.insert_once(session, retry)
            await session.commit()

    asyncio.run(run())


def test_creation_payload_conflict(pg_db):
    async def run():
        from datetime import date
        from api.tasks.create import CreationConflict, create
        from db.engine import get_session_maker

        async with get_session_maker()() as session:
            first, created = await create(session, creation_key='key', title='Example', start=date(2024, 1, 1))
            assert created
            await session.commit()
        async with get_session_maker()() as session:
            second, created = await create(session, creation_key='key', title='Example', start=date(2024, 1, 1))
            assert not created and first.id == second.id
            with pytest.raises(CreationConflict):
                await create(session, creation_key='key', title='Different', start=date(2024, 1, 1))
            await session.rollback()

    asyncio.run(run())


def test_creation_validates_source_account_and_message(pg_db):
    async def run():
        from datetime import date
        from api.tasks.create import create
        from db.engine import get_session_maker
        from db.models.mail_account import MailAccount
        from db.models.mail_message import MailMessage

        account = MailAccount(provider='imap', auth_type='imap_password', email_address='person@example.org')
        message = MailMessage(account_id=account.id, provider_uid='synthetic')
        async with get_session_maker()() as session:
            session.add(account)
            session.add(message)
            await session.commit()
        async with get_session_maker()() as session:
            row, created = await create(session, creation_key='source', title='Example', start=date(2024, 1, 1),
                                        source_account_id=account.id, source_message_id=message.id)
            assert created and row.source_message_id == message.id
            with pytest.raises(ValueError):
                await create(session, creation_key='invalid', title='Example', start=date(2024, 1, 1),
                             source_account_id=account.id, source_message_id='missing')
            await session.commit()

    asyncio.run(run())


def test_parallel_reconcile_materializes_each_occurrence_once(pg_db):
    async def run():
        from sqlalchemy import select
        from api.tasks.reconcile import ReconcileConflict, reconcile_batch
        from db.accessors import task_schedule_revision, task_series
        from db.engine import get_session_maker
        from db.models.task_occurrence import TaskOccurrence
        from db.models.task_schedule_revision import TaskScheduleRevision
        from db.models.task_series import TaskSeries

        series = TaskSeries(scope='app', creation_key='retry', creation_hash='hash', title='Example')
        revision = TaskScheduleRevision(series_id=series.id, version=1, start_local='2024-01-01', rrule='FREQ=DAILY')
        async with get_session_maker()() as session:
            await task_series.create_once(session, series)
            await task_schedule_revision.add(session, revision)
            await session.commit()

        async def worker():
            cursor = None
            while True:
                async with get_session_maker()() as session:
                    try:
                        cursor, done = await reconcile_batch(session, scope='app', series_id=series.id,
                            revision_id=revision.id, started_at=datetime(2024, 2, 10, tzinfo=UTC), cursor=cursor, limit=7)
                        await session.commit()
                    except ReconcileConflict:
                        await session.rollback()
                        current = await task_schedule_revision.get(session, revision.id)
                        cursor = current.reconcile_cursor
                        continue
                if done:
                    return

        await asyncio.gather(worker(), worker())
        async with get_session_maker()() as session:
            rows = (await session.execute(select(TaskOccurrence).where(TaskOccurrence.revision_id == revision.id))).scalars().all()
            assert len(rows) == 71
            assert len({row.occurrence_key for row in rows}) == 71
            assert min(row.occurrence_key for row in rows) == '2024-01-01'
            assert max(row.occurrence_key for row in rows) == '2024-03-11'

    asyncio.run(run())


def test_occurrence_list_scope_filters_and_cursor(pg_db):
    async def run():
        from db.accessors import task_occurrence, task_series
        from db.engine import get_session_maker
        from db.models.task_occurrence import TaskOccurrence
        from db.models.task_series import TaskSeries

        first = TaskSeries(scope='app', creation_key='first', creation_hash='hash', title='Example')
        other = TaskSeries(scope='other', creation_key='second', creation_hash='hash', title='Example')
        async with get_session_maker()() as session:
            await task_series.create_once(session, first)
            await task_series.create_once(session, other)
            for series, key in ((first, '2024-01-01'), (first, '2024-01-02'), (other, '2024-01-02')):
                await task_occurrence.insert_once(session, TaskOccurrence(series_id=series.id, revision_id=series.id, occurrence_key=key, due_local=key))
            await session.commit()
        async with get_session_maker()() as session:
            kwargs = dict(scope='app', status='open', due_from='2024-01-01', due_to='2024-01-03', limit=1)
            page = await task_occurrence.list_page(session, after=None, **kwargs)
            assert [row.due_local for row in page] == ['2024-01-01']
            next_page = await task_occurrence.list_page(session, after=(page[0].due_local, page[0].id), **kwargs)
            assert [row.due_local for row in next_page] == ['2024-01-02']
            assert await task_occurrence.list_page(session, after=(next_page[0].due_local, next_page[0].id), **kwargs) == []

    asyncio.run(run())


def test_domain_state_transitions_and_conflicts(pg_db):
    async def run():
        from api.tasks.state import StateConflict, transition
        from db.accessors import task_occurrence, task_series
        from db.engine import get_session_maker
        from db.models.task_occurrence import TaskOccurrence
        from db.models.task_series import TaskSeries

        series = TaskSeries(scope='app', creation_key='state', creation_hash='hash', title='Example')
        row = TaskOccurrence(series_id=series.id, revision_id='revision', occurrence_key='2024-01-01', due_local='2024-01-01')
        async with get_session_maker()() as session:
            await task_series.create_once(session, series)
            await task_occurrence.insert_once(session, row)
            await session.commit()
        async with get_session_maker()() as session:
            assert (await transition(session, row.id, version=1, action='complete')).version == 2
            assert (await transition(session, row.id, version=1, action='complete')).status == 'completed'
            with pytest.raises(StateConflict):
                await transition(session, row.id, version=1, action='reopen')
            assert (await transition(session, row.id, version=2, action='reopen')).status == 'open'
            await session.commit()

    asyncio.run(run())


def test_complete_skip_compare_and_swap_has_one_winner(pg_db):
    async def run():
        from db.accessors import task_occurrence
        from db.engine import get_session_maker
        from db.models.task_occurrence import TaskOccurrence

        row = TaskOccurrence(series_id='series-1', revision_id='revision-1', occurrence_key='2024-01-01', due_local='2024-01-01')
        async with get_session_maker()() as session:
            assert await task_occurrence.insert_once(session, row)
            await session.commit()

        async def attempt(target):
            async with get_session_maker()() as session:
                won = await task_occurrence.transition(session, row.id, version=1, expected='open', target=target)
                await session.commit()
                return won

        assert sum(await asyncio.gather(attempt('completed'), attempt('skipped'))) == 1
        async with get_session_maker()() as session:
            stored = await task_occurrence.get(session, row.id)
            assert stored.status in {'completed', 'skipped'} and stored.version == 2

    asyncio.run(run())
