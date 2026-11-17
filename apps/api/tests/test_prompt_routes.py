"""HTTP prompt contracts, including shared initial selection and conflict statuses."""
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from conftest import build_app
from db.accessors import prompt_template as p, prompt_revision as r
from db.models.prompt_template import PromptTemplate


@pytest.fixture
def library(monkeypatch):
    rows, revisions = {}, {}
    async def create(name, content):
        row = PromptTemplate(name=name, revision_id='')
        rev = p.revision(row.id, 1, content)
        row.revision_id = rev.id
        rows[row.id], revisions[rev.id] = row, rev
        return row
    async def change(id, expected_version, *, name=None, content=None, delete=False):
        row = rows.get(id)
        if not row: return None
        if expected_version != row.version: raise p.StaleVersion
        if delete:
            rows.pop(id)
            return row
        row.version += 1
        rev = p.revision(id, row.version, content or revisions[row.revision_id].content)
        row.revision_id = rev.id
        revisions[rev.id] = rev
        if name is not None: row.name = name
        return row
    monkeypatch.setattr(p, 'create_template', create)
    monkeypatch.setattr(p, 'change_template', change)
    monkeypatch.setattr(p, 'get_template', AsyncMock(side_effect=lambda id: rows.get(id)))
    monkeypatch.setattr(p, 'list_templates', AsyncMock(side_effect=lambda: list(rows.values())))
    monkeypatch.setattr(r, 'get_revision', AsyncMock(side_effect=lambda id: revisions.get(id)))
    monkeypatch.setattr(r, 'list_revisions', AsyncMock(side_effect=lambda id: sorted(
        [rev for rev in revisions.values() if rev.template_id == id], key=lambda rev: -rev.number)))
    return TestClient(build_app()), revisions


def test_crud_revision_and_versions(library):
    client, revisions = library
    response = client.post('/api/v1/prompts', json={'name': 'Test', 'text': 'Erster Text', 'owner_scope': 'untrusted'})
    assert response.status_code == 201
    first = response.json()
    path = '/api/v1/prompts/' + first['id']
    detail = client.get(path).json()
    assert detail.pop('revisions')[0]['id'] == first['revision_id']
    assert detail == first
    assert client.get('/api/v1/prompts').json() == [first]
    second = client.patch(path, json={'expected_version': 1, 'text': 'Zweiter Text'}).json()
    assert second['revision_id'] != first['revision_id'] and second['version'] == 2
    assert revisions[first['revision_id']].content == 'Erster Text'
    assert [rev['number'] for rev in client.get(path).json()['revisions']] == [2, 1]
    assert revisions[first['revision_id']].owner_scope == 'installation'
    assert client.patch(path, json={'expected_version': 1, 'text': 'Veraltet'}).status_code == 409
    assert client.delete(path + '?expected_version=1').status_code == 409
    assert client.delete(path).status_code == 422
    assert client.delete(path + '?expected_version=2').status_code == 204
    assert client.get(path).status_code == 404


@pytest.mark.parametrize('path,body', [('/api/v1/chat', {'message': 'Hallo'}),
                                      ('/api/v1/chat/stream', {'text': 'Hallo'})])
def test_both_entries_forward_selection(path, body, monkeypatch):
    from api.mail import agent
    from api.routers.api.v1.chat import stream
    from api.mail.chat_events import StartEvent, DoneEvent
    from db.accessors import chat_message
    seen = []
    async def run(**kwargs):
        seen.append(kwargs)
        yield StartEvent(conversation_id='c', user_message_id='u')
        yield DoneEvent(conversation_id='c', message_id='m', stopped=False)
    monkeypatch.setattr(agent, 'run_turn_events', run)
    monkeypatch.setattr(stream, 'run_turn_events', run)
    monkeypatch.setattr(stream, 'resolve_context', AsyncMock(return_value=('snapshot',)))
    monkeypatch.setattr(chat_message, 'list_messages', AsyncMock(return_value=[]))
    body.update(prompt_revision_id='revision', account_id='account')
    response = TestClient(build_app()).post(path, json=body)
    assert response.status_code == 200
    assert seen[0]['prompt_revision_id'] == 'revision' and seen[0]['account_id'] == 'account'
