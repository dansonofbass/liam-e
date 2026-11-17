"""PATCH validation, conflict codes and caller transaction boundaries."""

import importlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from api.tasks.patch import RevisionConflict
from api.tasks.state import StateConflict, StateNotFound


@pytest.fixture
def patch_access(monkeypatch):
    route = importlib.import_module('api.routers.api.v1.tasks.[series_id]')
    session = AsyncMock()

    @asynccontextmanager
    async def open_session():
        yield session

    monkeypatch.setattr(route, 'get_session_maker', lambda: open_session)
    change = AsyncMock(return_value=(2, 'revision'))
    monkeypatch.setattr(route, 'patch', change)
    return session, change


def test_patch_response_and_distinct_errors(client, patch_access):
    session, change = patch_access
    body = {'expected_version': 1, 'expected_occurrence_version': 1,
            'occurrence_id': 'o', 'scope': 'this_and_following', 'start': '2024-01-10'}
    response = client.patch('/api/v1/tasks/s', json=body)
    assert response.status_code == 200 and response.json() == {'id': 's', 'version': 2, 'revision_id': 'revision'}
    session.commit.assert_awaited_once()
    assert change.await_args.kwargs['rule_supplied'] is False
    assert client.patch('/api/v1/tasks/s', json={**body, 'rrule': None}).status_code == 200
    assert change.await_args.kwargs['rule_supplied'] is True
    for error, status, code in [(RevisionConflict(), 409, 'task_revision_conflict'),
                                (StateConflict(), 409, 'task_version_conflict'),
                                (StateNotFound(), 404, 'task_not_found'),
                                (ValueError(), 422, 'task_invalid')]:
        change.side_effect = error
        response = client.patch('/api/v1/tasks/s', json=body)
        assert response.status_code == status and code in response.text
    assert session.commit.await_count == 2
    assert client.patch('/api/v1/tasks/s', json={**body, 'scope': 'all'}).status_code == 422
    assert client.patch('/api/v1/tasks/s', json={**body, 'expected_occurrence_version': 0}).status_code == 422
    assert client.patch('/api/v1/tasks/s', json={**body, 'title': 'Unsupported'}).status_code == 422
