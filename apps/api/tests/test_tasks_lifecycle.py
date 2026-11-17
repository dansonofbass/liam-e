"""Explicit final-delete confirmation and versioned lifecycle HTTP errors."""

import importlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from db.models.task_series import TaskSeries

from api.tasks.lifecycle import DeleteConfirmationRequired
from api.tasks.state import StateConflict, StateNotFound


def test_lifecycle_confirmation_versions_and_commit(client, monkeypatch):
    route = importlib.import_module('api.routers.api.v1.tasks.[series_id]')
    session = AsyncMock()

    @asynccontextmanager
    async def open_session():
        yield session

    monkeypatch.setattr(route, 'get_session_maker', lambda: open_session)
    archive = AsyncMock(return_value=TaskSeries(id='s', scope='app', creation_key='k',
        creation_hash='h', title='Example', archived=True, version=2))
    delete = AsyncMock()
    monkeypatch.setattr(route.lifecycle, 'archive', archive)
    monkeypatch.setattr(route.lifecycle, 'delete', delete)
    response = client.post('/api/v1/tasks/s/archive', json={'expected_version': 1})
    assert response.status_code == 200 and response.json()['version'] == 2
    session.commit.assert_awaited_once()
    archive.side_effect = StateConflict()
    assert client.post('/api/v1/tasks/s/archive', json={'expected_version': 1}).status_code == 409
    archive.side_effect = StateNotFound()
    assert client.post('/api/v1/tasks/s/archive', json={'expected_version': 1}).status_code == 404
    delete.side_effect = DeleteConfirmationRequired()
    response = client.request('DELETE', '/api/v1/tasks/s', json={'expected_version': 2})
    assert response.status_code == 422 and 'task_delete_confirmation_required' in response.text
    assert delete.await_args.kwargs['confirm_history_loss'] is False
    delete.side_effect = None
    assert client.request('DELETE', '/api/v1/tasks/s', json={
        'expected_version': 2, 'confirm_history_loss': True,
    }).status_code == 204
    assert session.commit.await_count == 2
    assert client.request('DELETE', '/api/v1/tasks/s', json={
        'expected_version': 2, 'confirm_history_loss': 'true',
    }).status_code == 422
