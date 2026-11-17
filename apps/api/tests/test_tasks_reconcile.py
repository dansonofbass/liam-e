"""The explicit materialization endpoint owns only the outer transaction."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from api.routers.api.v1.tasks import reconcile
from api.tasks.reconcile import ReconcileConflict


def test_reconcile_response_and_conflict(client, monkeypatch):
    session = AsyncMock()

    @asynccontextmanager
    async def open_session():
        yield session

    monkeypatch.setattr(reconcile, 'get_session_maker', lambda: open_session)
    call = AsyncMock(return_value=('r', '{"target":"2024-01-31T00:00:00+00:00"}', False))
    monkeypatch.setattr(reconcile, 'reconcile_current', call)
    response = client.post('/api/v1/tasks/reconcile', json={'series_id': 's', 'limit': 7})
    assert response.status_code == 200
    assert response.json()['complete'] is False
    assert response.json()['revision_id'] == 'r'
    assert call.await_args.kwargs == {'series_id': 's', 'revision_id': None, 'cursor': None, 'advance': False, 'limit': 7}
    session.commit.assert_awaited_once()
    call.side_effect = ReconcileConflict('synthetic')
    assert client.post('/api/v1/tasks/reconcile', json={'series_id': 's', 'cursor': 'old'}).status_code == 409
    assert session.commit.await_count == 1
    assert client.post('/api/v1/tasks/reconcile', json={'series_id': 's', 'scope': 'other'}).status_code == 422
    assert client.post('/api/v1/tasks/reconcile', json={'series_id': 's', 'limit': 101}).status_code == 422
