"""SSE route and pump contracts."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from conftest import build_app
from test_chat_agent import store  # noqa: F401
from support.fake_mistral import FakeMistral
from api.mail import agent


@pytest.fixture(autouse=True)
def mock_context_resolution(monkeypatch):
    from api.routers.api.v1.chat import stream
    monkeypatch.setattr(stream, 'resolve_context', AsyncMock(return_value=None))


def test_stream_emits_sse_frames(monkeypatch):
    from api.routers.api.v1.chat import stream
    from api.mail.chat_events import StartEvent, DeltaEvent, DoneEvent

    async def fake(**kwargs):
        yield StartEvent(conversation_id='c', user_message_id='u')
        yield DeltaEvent(text='Hallo')
        yield DoneEvent(conversation_id='c', message_id='m', stopped=False)
    monkeypatch.setattr(stream, 'run_turn_events', fake)
    with TestClient(build_app()).stream('POST', '/api/v1/chat/stream', json={'text': 'Hallo'}) as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        lines = list(response.iter_lines())
    assert [line for line in lines if line.startswith('event:')] == ['event: start', 'event: delta', 'event: done']
    assert [json.loads(line[5:])['event'] for line in lines if line.startswith('data:')] == ['start', 'delta', 'done']


def _model_stream_app(monkeypatch, *, known=('valid',)):
    from api.routers.api.v1.chat import stream
    from api.mail.chat_events import DoneEvent
    from api.mail.models_catalog import ChatModelOut
    seen = []
    async def fake(**kwargs):
        seen.append(kwargs)
        yield DoneEvent(conversation_id='c', message_id='m', stopped=False)
    async def models(): return [ChatModelOut(id=name, label=name, description='', is_default=False) for name in known]
    monkeypatch.setattr(stream, 'run_turn_events', fake)
    monkeypatch.setattr(stream, 'list_chat_models', models)
    return TestClient(build_app()), seen


def test_stream_passes_a_known_model_to_a_new_conversation(monkeypatch):
    client, seen = _model_stream_app(monkeypatch)
    with client.stream('POST', '/api/v1/chat/stream', json={'text': 'Hallo', 'model': 'valid'}) as response:
        assert response.status_code == 200
        list(response.iter_lines())
    assert seen[0]['model'] == 'valid' and seen[0]['conversation_id'] is None
    with client.stream('POST', '/api/v1/chat/stream', json={'text': 'Hallo'}) as response:
        list(response.iter_lines())
    assert seen[1]['model'] is None


def test_stream_refuses_an_unknown_model_before_it_starts(monkeypatch):
    client, seen = _model_stream_app(monkeypatch)
    response = client.post('/api/v1/chat/stream', json={'text': 'Hallo', 'model': 'gone'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'model_unknown'
    assert seen == []


def test_stream_does_not_check_the_model_of_an_existing_conversation(monkeypatch):
    from db.accessors import chat_conversation
    from unittest.mock import AsyncMock
    monkeypatch.setattr(chat_conversation, 'get_conversation', AsyncMock(return_value=object()))
    client, seen = _model_stream_app(monkeypatch)
    with client.stream('POST', '/api/v1/chat/stream', json={'text': 'Hallo', 'conversation_id': 'c', 'model': 'gone'}) as response:
        assert response.status_code == 200
        list(response.iter_lines())
    assert seen[0]['conversation_id'] == 'c'


@pytest.mark.anyio
async def test_stream_disconnect_marks_answer_stopped(store, monkeypatch):
    from api.routers.api.v1.chat.stream import sse_frames
    monkeypatch.setattr(agent, 'mistral_client', lambda: FakeMistral(streams=[['Teil', ' weiter']]))
    disconnected = False
    async def check(): return disconnected
    frames = sse_frames(agent.run_turn_events(conversation_id=None, text='Hallo'), check)
    async for frame in frames:
        if 'event: delta' in frame:
            disconnected = True
    assert store.rows[-1].content == 'Teil' and store.rows[-1].stopped


@pytest.mark.anyio
async def test_ping_keeps_pending_step_alive():
    from api.routers.api.v1.chat.stream import sse_frames
    from api.mail.chat_events import DeltaEvent
    cancelled = False
    async def slow():
        nonlocal cancelled
        try:
            await asyncio.sleep(0.04)
            yield DeltaEvent(text='ok')
        except asyncio.CancelledError:
            cancelled = True
            raise
    frames = [frame async for frame in sse_frames(slow(), AsyncMock(return_value=False), ping_seconds=0.01)]
    assert ': ping\n\n' in frames and any('event: delta' in frame for frame in frames)
    assert not cancelled


def test_stream_schema_exports_chat_event():
    schema = build_app().openapi()
    response = schema['paths']['/api/v1/chat/stream']['post']['responses']['200']['content']
    assert set(response) == {'text/event-stream'}
    assert response['text/event-stream']['schema'] == {'$ref': '#/components/schemas/ChatEvent'}
    components = schema['components']['schemas']
    assert len(components['ChatEvent']['oneOf']) == 9
    assert 'CalendarsEvent' in components
    assert components['ChatEvent']['discriminator']['propertyName'] == 'event'
    for name in ('StartEvent', 'StatusEvent', 'DeltaEvent', 'MailsEvent', 'ProposalEvent', 'SuggestionsEvent', 'DoneEvent', 'ErrorEvent'):
        assert set(components[name]['properties']) == set(components[name]['required'])
    assert 'MailRefOut' in components and 'ChatMessageOut' in components
