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
    assert len(components['ChatEvent']['oneOf']) == 8
    assert components['ChatEvent']['discriminator']['propertyName'] == 'event'
    for name in ('StartEvent', 'StatusEvent', 'DeltaEvent', 'MailsEvent', 'ProposalEvent', 'SuggestionsEvent', 'DoneEvent', 'ErrorEvent'):
        assert set(components[name]['properties']) == set(components[name]['required'])
    assert 'MailRefOut' in components and 'ChatMessageOut' in components
