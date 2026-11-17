"""Private validation and conflict responses do not echo preference values."""
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from conftest import build_app
from db.accessors import user_preference as p
from db.models.personalization_settings import PersonalizationSettings


@pytest.mark.parametrize('body', [
    {'key': 'signature', 'value': 'test-only', 'owner_scope': 'other'},
    {'key': 'profile', 'value': 'test-only'},
    {'key': 'answer_length', 'value': 'test-only' * 100},
])
def test_invalid_content_is_private(body, caplog):
    result = TestClient(build_app()).post('/api/v1/preferences', json=body)
    assert result.status_code == 422
    assert 'test-only' not in result.text + caplog.text


def test_conflicts_and_storage_errors_are_private(monkeypatch, caplog):
    client = TestClient(build_app())
    for error, status in [(p.StaleVersion(), 409), (p.PreferenceConflict(), 409),
                          (SQLAlchemyError('test-only'), 503)]:
        monkeypatch.setattr(p, 'change', AsyncMock(side_effect=error))
        response = client.patch('/api/v1/preferences/id', json={'expected_version': 1, 'value': 'test-only'})
        assert response.status_code == status
        assert 'test-only' not in response.text + caplog.text


def test_settings_partial_update_and_disabled_suggestions(monkeypatch):
    client = TestClient(build_app())
    monkeypatch.setattr(p, 'settings', AsyncMock(return_value=PersonalizationSettings()))
    update = AsyncMock(return_value=PersonalizationSettings(use_preferences=True, version=2))
    monkeypatch.setattr(p, 'update_settings', update)
    assert client.get('/api/v1/settings').json() == {'personalization': {
        'use_preferences': False, 'suggest_preferences': False, 'version': 1}}
    response = client.patch('/api/v1/settings', json={'personalization': {'expected_version': 1, 'use_preferences': True}})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    update.assert_awaited_once_with(expected_version=1, use_preferences=True)
    for body in [{'personalization': {'expected_version': 2, 'suggest_preferences': True}},
                 {'personalization': {'expected_version': 2, 'use_preferences': None}},
                 {'personalization': {'expected_version': 2}, 'ui': {}}]:
        assert client.patch('/api/v1/settings', json=body).status_code == 422
