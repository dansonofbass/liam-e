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
            first, created = await create(session, creation_key='key', title='Example', start=date(2024, 1, 1), zone='UTC')
            assert created
            await session.commit()
        async with get_session_maker()() as session:
            second, created = await create(session, creation_key='key', title='Example', start=date(2024, 1, 1), zone='UTC')
            assert not created and first.id == second.id
            with pytest.raises(CreationConflict):
                await create(session, creation_key='key', title='Different', start=date(2024, 1, 1), zone='UTC')
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
            row, created = await create(session, creation_key='source', title='Example', start=date(2024, 1, 1), zone='UTC',
                                        source_account_id=account.id, source_message_id=message.id)
            assert created and row.source_message_id == message.id
            with pytest.raises(ValueError):
                await create(session, creation_key='invalid', title='Example', start=date(2024, 1, 1), zone='UTC',
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


def test_legacy_count_completion_replays_without_changing_existing_instances(pg_db):
    async def run():
        import json
        from datetime import timedelta
        from api.tasks.create import create
        from api.tasks.reconcile import reconcile_batch
        from api.tasks.recurrence import expand
        from db.accessors import task_occurrence, task_schedule_revision
        from db.engine import get_session_maker
        from db.models.task_occurrence import TaskOccurrence

        start = datetime(2024, 3, 30, 2, 30)
        started = datetime(2024, 3, 20, tzinfo=UTC)
        target = (started + timedelta(days=30)).isoformat()
        async with get_session_maker()() as session:
            series, _ = await create(session, creation_key='legacy-count', title='Example',
                                     start=start, zone='Europe/Berlin', rule='FREQ=DAILY;COUNT=3')
            revision = await task_schedule_revision.get_by_version(session, series.id, 1)
            cursor = json.dumps({'revision': revision.id, 'target': target, 'position': 'done'})
            revision.reconcile_target = target
            revision.reconcile_cursor = cursor
            session.add(revision)
            old = []
            for key in ('2024-03-30T02:30:00', '2024-04-01T02:30:00'):
                row = TaskOccurrence(series_id=series.id, revision_id=revision.id,
                                     occurrence_key=key, due_local=key, status='completed', version=2)
                await task_occurrence.insert_once(session, row)
                old.append(row.id)
            await session.commit()
        pages = 0
        while True:
            async with get_session_maker()() as session:
                cursor, done = await reconcile_batch(session, scope='app', series_id=series.id,
                    revision_id=revision.id, started_at=started, cursor=cursor, limit=1)
                await session.commit()
            pages += 1
            assert pages <= 5
            if done:
                break
        async with get_session_maker()() as session:
            rows = await task_occurrence.list_page(session, scope='app', status=None,
                                                  due_from=None, due_to=None, after=None, limit=100)
            expected = expand(start, 'FREQ=DAILY;COUNT=3', datetime(2024, 4, 19), 'Europe/Berlin')
            assert [row.occurrence_key for row in rows] == [v.replace(tzinfo=None).isoformat() for v in expected]
            assert [(row.id, row.status, row.version) for row in rows[:2]] == [(identifier, 'completed', 2) for identifier in old]
            assert rows[-1].status == 'open'
            assert await reconcile_batch(session, scope='app', series_id=series.id,
                revision_id=revision.id, started_at=started, cursor=cursor, limit=1) == (cursor, True)

    asyncio.run(run())


@pytest.mark.parametrize('local_start,rule,started', [
    ('2024-03-30T02:30:00', 'FREQ=DAILY;COUNT=3', datetime(2024, 3, 10, tzinfo=UTC)),
    ('2024-10-26T02:30:00', 'FREQ=DAILY;COUNT=3', datetime(2024, 10, 10, tzinfo=UTC)),
    ('2024-01-31', 'FREQ=MONTHLY;COUNT=3', datetime(2024, 5, 10, tzinfo=UTC)),
    ('2023-12-29', 'FREQ=MONTHLY;COUNT=4', datetime(2024, 3, 10, tzinfo=UTC)),
    ('2024-01-01', 'FREQ=DAILY;UNTIL=20240103', datetime(2024, 1, 1, tzinfo=UTC)),
])
def test_preview_and_persistence_share_calendar_fixtures(pg_db, local_start, rule, started):
    async def run():
        from datetime import date, timedelta
        from zoneinfo import ZoneInfo
        from api.tasks.create import create
        from api.tasks.preview import preview
        from api.tasks.reconcile import reconcile_current
        from db.accessors import task_occurrence
        from db.engine import get_session_maker

        timed = 'T' in local_start
        start = datetime.fromisoformat(local_start) if timed else date.fromisoformat(local_start)
        through = (started + timedelta(days=30)).astimezone(ZoneInfo('Europe/Berlin'))
        end = through.replace(tzinfo=None) if timed else through.date()
        expected = preview(start, rule, end, 'Europe/Berlin')['occurrences']
        async with get_session_maker()() as session:
            series, _ = await create(session, creation_key='parity', title='Example', start=start,
                                     rule=rule, zone='Europe/Berlin')
            await session.commit()
        cursor = None
        for _ in range(10):
            async with get_session_maker()() as session:
                _, cursor, done = await reconcile_current(session, series_id=series.id, cursor=cursor, limit=2, now=started)
                await session.commit()
            if done:
                break
        assert done
        async with get_session_maker()() as session:
            rows = await task_occurrence.list_page(session, scope='app', status=None,
                due_from=None, due_to=None, after=None, limit=100)
            assert [row.occurrence_key for row in rows] == expected
            assert all((row.due_at is not None) == timed for row in rows)

    asyncio.run(run())


def test_reconcile_rollback_resume_advance_and_stale_cursor(pg_db):
    async def run():
        from datetime import date
        from api.tasks.create import create
        from api.tasks.reconcile import ReconcileConflict, reconcile_current
        from db.accessors import task_occurrence, task_schedule_revision
        from db.engine import get_session_maker

        now = datetime(2024, 1, 1, tzinfo=UTC)
        async with get_session_maker()() as session:
            series, _ = await create(session, creation_key='resume', title='Example',
                                     start=date(2024, 1, 1), zone='UTC', rule='FREQ=DAILY')
            await session.commit()
        async with get_session_maker()() as session:
            await reconcile_current(session, series_id=series.id, now=now, limit=7)
            await session.rollback()
        async with get_session_maker()() as session:
            revision = await task_schedule_revision.current(session, series.id)
            assert revision.reconcile_cursor is None
            assert await task_occurrence.list_page(session, scope='app', status=None,
                due_from=None, due_to=None, after=None, limit=100) == []
            _, first, done = await reconcile_current(session, series_id=series.id, now=now, limit=7)
            assert not done
            await session.commit()
        async with get_session_maker()() as session:
            with pytest.raises(ReconcileConflict):
                await reconcile_current(session, series_id=series.id, cursor=first, advance=True,
                                        now=datetime(2024, 2, 10, tzinfo=UTC))
            await session.rollback()
        # Omitted cursors recover the durable position after client restarts.
        for _ in range(10):
            async with get_session_maker()() as session:
                _, cursor, done = await reconcile_current(session, series_id=series.id, limit=7)
                await session.commit()
            if done:
                break
        assert done
        async with get_session_maker()() as session:
            with pytest.raises(ReconcileConflict):
                await reconcile_current(session, series_id=series.id, cursor=first)
            await session.rollback()
            _, advanced, done = await reconcile_current(session, series_id=series.id, cursor=cursor,
                advance=True, now=datetime(2024, 2, 10, tzinfo=UTC), limit=7)
            assert not done and advanced != cursor
            await session.commit()
        async with get_session_maker()() as session:
            with pytest.raises(ReconcileConflict):
                await reconcile_current(session, series_id=series.id, cursor=cursor, advance=True,
                                        now=datetime(2024, 2, 10, tzinfo=UTC))
            await session.rollback()
        for _ in range(10):
            async with get_session_maker()() as session:
                _, cursor, done = await reconcile_current(session, series_id=series.id, limit=7)
                await session.commit()
            if done:
                break
        assert done
        async with get_session_maker()() as session:
            rows = await task_occurrence.list_page(session, scope='app', status=None,
                due_from=None, due_to=None, after=None, limit=100)
            assert len(rows) == 71
            assert len({row.occurrence_key for row in rows}) == 71
            assert rows[-1].due_local == '2024-03-11'
            with pytest.raises(ReconcileConflict):
                await reconcile_current(session, series_id=series.id, revision_id='other')
            with pytest.raises(ReconcileConflict):
                await reconcile_current(session, series_id='other')

    asyncio.run(run())


def test_creation_rolls_back_when_materialization_fails(pg_db, monkeypatch):
    from datetime import date
    from api.main import create_app
    from api.routers.api.v1.tasks import route
    from fastapi.testclient import TestClient
    from mistralai_capabilities.fastapi.hooks import FastAPIHooks

    async def fail(*args, **kwargs):
        raise RuntimeError('synthetic failure')

    original = route.reconcile.reconcile_batch
    monkeypatch.setattr(route.reconcile, 'reconcile_batch', fail)
    app = create_app(hooks=FastAPIHooks.empty())
    body = {'creation_key': 'rollback', 'title': 'Example', 'start': date.today().isoformat(), 'timezone': 'UTC'}
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post('/api/v1/tasks', json=body).status_code == 500
        assert client.get('/api/v1/tasks/occurrences').json()['items'] == []
        monkeypatch.setattr(route.reconcile, 'reconcile_batch', original)
        retry = client.post('/api/v1/tasks', json=body)
        assert retry.status_code == 200 and retry.json()['created'] is True


def test_created_task_is_immediately_visible_via_api(pg_db):
    from datetime import date
    from api.main import create_app
    from fastapi.testclient import TestClient
    from mistralai_capabilities.fastapi.hooks import FastAPIHooks

    app = create_app(hooks=FastAPIHooks.empty())
    body = {'creation_key': 'api-create', 'title': 'Example', 'start': date.today().isoformat(), 'timezone': 'UTC'}
    with TestClient(app) as client:
        first = client.post('/api/v1/tasks', json=body)
        assert first.status_code == 200 and first.json()['created'] is True
        visible = client.get('/api/v1/tasks/occurrences')
        assert visible.status_code == 200
        assert len(visible.json()['items']) == 1
        assert visible.json()['items'][0]['series_id'] == first.json()['id']
        retry = client.post('/api/v1/tasks', json=body)
        assert retry.status_code == 200 and retry.json()['created'] is False
        assert len(client.get('/api/v1/tasks/occurrences').json()['items']) == 1


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


def test_series_reads_are_scoped_paginated_and_never_write_even_after_source_removal(pg_db):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from api.main import create_app
    from fastapi.testclient import TestClient
    from mistralai_capabilities.fastapi.hooks import FastAPIHooks

    async def seed():
        from datetime import date
        from api.tasks.create import create
        from api.tasks.reconcile import reconcile_current
        from db.accessors import task_series
        from db.engine import get_session_maker
        from db.models.mail_account import MailAccount
        from db.models.mail_message import MailMessage
        from db.models.task_series import TaskSeries

        account = MailAccount(provider='imap', auth_type='imap_password', email_address='source@example.org')
        message = MailMessage(account_id=account.id, provider_uid='synthetic')
        async with get_session_maker()() as session:
            session.add(account)
            session.add(message)
            await session.flush()
            linked, _ = await create(session, creation_key='linked', title='Linked', start=date(2024, 1, 1),
                zone='UTC', rule='FREQ=DAILY', source_account_id=account.id, source_message_id=message.id)
            unlinked, _ = await create(session, creation_key='unlinked', title='Unlinked', start=date(2024, 1, 1), zone='UTC')
            later, _ = await create(session, creation_key='later', title='Later', start=date(2025, 1, 1), zone='UTC')
            hidden = TaskSeries(scope='other', creation_key='hidden', creation_hash='hash', title='Hidden')
            await task_series.create_once(session, hidden)
            await reconcile_current(session, series_id=linked.id, now=datetime(2024, 1, 1, tzinfo=UTC))
            unlinked.archived = True
            session.add(unlinked)
            await session.delete(message)
            await session.delete(account)
            await session.commit()
            identifiers = linked.id, unlinked.id, later.id, hidden.id, account.id, message.id
        from db.engine import dispose_engine
        await dispose_engine()
        return identifiers

    linked, unlinked, later, hidden, account, message = asyncio.run(seed())
    statements = []

    def read_only(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert statement.lstrip().upper().startswith('SELECT'), 'GET attempted a write'
        assert 'FOR UPDATE' not in statement.upper(), 'GET attempted to lock rows'

    app = create_app(hooks=FastAPIHooks.empty())
    window = {'due_from': '2024-01-01', 'due_to': '2024-01-31'}
    with TestClient(app) as client:
        event.listen(Engine, 'before_cursor_execute', read_only)
        try:
            first = client.get('/api/v1/tasks', params={**window, 'limit': 1}).json()
            assert len(first['items']) == 1 and first['next_cursor']
            second = client.get('/api/v1/tasks', params={**window, 'limit': 1, 'cursor': first['next_cursor']}).json()
            assert second['next_cursor'] is None
            assert {first['items'][0]['id'], second['items'][0]['id']} == {linked, unlinked}
            result = client.get('/api/v1/tasks', params={**window, 'source': 'account', 'source_account_id': account}).json()
            assert [row['id'] for row in result['items']] == [linked]
            assert result['items'][0]['complete']
            assert result['items'][0]['source_message_id'] == message
            assert client.get('/api/v1/tasks', params={**window, 'source': 'account'}).status_code == 422
            result = client.get('/api/v1/tasks', params={**window, 'source': 'unlinked', 'status': 'archived'}).json()
            assert [row['id'] for row in result['items']] == [unlinked]
            assert not result['items'][0]['complete']
            result = client.get('/api/v1/tasks', params={**window, 'status': 'active'}).json()
            assert [row['id'] for row in result['items']] == [linked]
            detail = client.get(f'/api/v1/tasks/{linked}', params={**window, 'limit': 2}).json()
            assert detail['series']['complete'] and len(detail['occurrences']['items']) == 2
            next_page = client.get(f'/api/v1/tasks/{linked}', params={**window, 'limit': 2,
                'cursor': detail['occurrences']['next_cursor']}).json()
            assert next_page['occurrences']['items'][0]['due_local'] == '2024-01-03'
            empty = client.get(f'/api/v1/tasks/{linked}', params={**window, 'status': 'completed'}).json()
            assert empty['occurrences']['items'] == [] and empty['series']['complete']
            outside = client.get(f'/api/v1/tasks/{linked}', params={**window, 'due_to': '2024-02-01'}).json()
            assert not outside['series']['complete']
            assert client.get(f'/api/v1/tasks/{hidden}', params=window).status_code == 404
            assert client.get('/api/v1/tasks/missing', params=window).status_code == 404
            assert client.get('/api/v1/tasks', params={**window, 'due_to': '2026-01-01'}).status_code == 422
            assert statements
        finally:
            event.remove(Engine, 'before_cursor_execute', read_only)


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
