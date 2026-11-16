from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from db.models.task_occurrence import TaskOccurrence
from db.models.task_series import TaskSeries

from api.routers.api.v1.tasks import occurrences, route
from api.tasks.create import CreationConflict
from api.tasks.state import StateConflict, StateNotFound


@pytest.fixture
def access(monkeypatch):
    session = AsyncMock()

    @asynccontextmanager
    async def open_session():
        yield session

    monkeypatch.setattr(route, 'get_session_maker', lambda: open_session)
    monkeypatch.setattr(occurrences, 'get_session_maker', lambda: open_session)
    create = AsyncMock(return_value=(TaskSeries(id='s', scope='app', creation_key='k', creation_hash='h', title='Example'), True))
    listing = AsyncMock(return_value=[])
    change = AsyncMock(return_value=TaskOccurrence(id='o', series_id='s', revision_id='r', occurrence_key='2024-01-01', due_local='2024-01-01'))
    monkeypatch.setattr(route.create, 'create', create)
    monkeypatch.setattr(route.task_schedule_revision, 'get_by_version', AsyncMock(return_value=type('Revision', (), {'id': 'r'})()))
    monkeypatch.setattr(route.reconcile, 'reconcile_batch', AsyncMock(return_value=(None, True)))
    monkeypatch.setattr(occurrences.task_occurrence, 'list_page', listing)
    monkeypatch.setattr(occurrences.state, 'transition', change)
    return session, create, listing, change


def test_creation_and_conflict(client, access):
    session, create, _, _ = access
    body = {'creation_key': 'k', 'title': 'Example', 'start': '2024-01-01'}
    response = client.post('/api/v1/tasks', json=body)
    assert response.status_code == 200 and response.json()['created'] is True
    session.commit.assert_awaited_once()
    create.side_effect = CreationConflict()
    assert client.post('/api/v1/tasks', json=body).status_code == 409
    assert client.post('/api/v1/tasks', json={**body, 'start': 'invalid'}).status_code == 422
    assert client.post('/api/v1/tasks', json={**body, 'creation_key': ''}).status_code == 422


@pytest.mark.parametrize(('start', 'kind'), [('2024-01-01', 'date'), ('2024-01-01T09:00', 'datetime'), ('2024-01-01t09:00', 'datetime')])
def test_start_precision_follows_the_input(client, access, start, kind):
    _, create, _, _ = access
    body = {'creation_key': 'k', 'title': 'Example', 'start': start, 'timezone': 'Europe/Berlin'}
    assert client.post('/api/v1/tasks', json=body).status_code == 200
    assert type(create.await_args.kwargs['start']).__name__ == kind


def test_new_task_is_visible_and_retry_does_not_reconcile_again(client, access):
    _, create, listing, _ = access
    row = TaskOccurrence(id='o', series_id='s', revision_id='r', occurrence_key='2024-01-01', due_local='2024-01-01')

    async def materialize(*args, **kwargs):
        listing.return_value = [row]
        return None, True

    route.reconcile.reconcile_batch.side_effect = materialize
    body = {'creation_key': 'k', 'title': 'Example', 'start': '2024-01-01'}
    assert client.post('/api/v1/tasks', json=body).status_code == 200
    response = client.get('/api/v1/tasks/occurrences')
    assert response.status_code == 200 and response.json()['items'][0]['id'] == 'o'
    series = create.return_value[0]
    create.return_value = (series, False)
    assert client.post('/api/v1/tasks', json=body).json()['created'] is False
    route.reconcile.reconcile_batch.assert_awaited_once()


def test_reconcile_failure_does_not_commit_creation(client, access):
    session, _, _, _ = access
    route.reconcile.reconcile_batch.side_effect = RuntimeError('synthetic failure')
    with pytest.raises(RuntimeError, match='synthetic failure'):
        client.post('/api/v1/tasks', json={'creation_key': 'k', 'title': 'Example', 'start': '2024-01-01'})
    session.commit.assert_not_awaited()


def test_list_filters_cursor_and_invalid_input(client, access):
    _, _, listing, _ = access
    row = TaskOccurrence(id='o', series_id='s', revision_id='r', occurrence_key='2024-01-01', due_local='2024-01-01')
    listing.return_value = [row, TaskOccurrence(id='p', series_id='s', revision_id='r', occurrence_key='2024-01-02', due_local='2024-01-02')]
    response = client.get('/api/v1/tasks/occurrences', params={'status': 'open', 'due_from': '2024-01-01', 'due_to': '2024-01-02', 'limit': 1})
    assert response.status_code == 200 and len(response.json()['items']) == 1
    cursor = response.json()['next_cursor']
    assert occurrences.decode_cursor(cursor) == ('2024-01-01', 'o')
    assert listing.await_args.kwargs['scope'] == 'app'
    assert listing.await_args.kwargs['due_to'] == '2024-01-03'
    assert client.get('/api/v1/tasks/occurrences', params={'cursor': '!!!'}).status_code == 422
    assert client.get('/api/v1/tasks/occurrences', params={'status': 'bad'}).status_code == 422
    assert client.get('/api/v1/tasks/occurrences', params={'due_from': '2024-01-02', 'due_to': '2024-01-01'}).status_code == 422
    assert client.get('/api/v1/tasks/occurrences', params={'limit': 101}).status_code == 422


@pytest.mark.parametrize('action', ['complete', 'skip', 'reopen'])
def test_transition_responses(client, access, action):
    _, _, _, change = access
    url = f'/api/v1/tasks/occurrences/o/{action}'
    assert client.post(url, json={'version': 1}).status_code == 200
    assert change.await_args.kwargs == {'version': 1, 'action': action}
    change.side_effect = StateConflict()
    assert client.post(url, json={'version': 1}).status_code == 409
    change.side_effect = StateNotFound()
    assert client.post(url, json={'version': 1}).status_code == 404
    assert client.post(url, json={'version': 0}).status_code == 422
