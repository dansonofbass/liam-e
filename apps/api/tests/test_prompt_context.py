"""Prompt boundary, paused-stream and privacy contracts with synthetic content."""
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from conftest import build_app
from test_chat_agent import store, chunk
from api.mail import agent, context_resolver
from support.fake_mistral import FakeMistral


@pytest.mark.anyio
@pytest.mark.parametrize('error,status,code', [
    (context_resolver.chat_context.ScopeChange(), 409, 'conversation_scope_change_requires_new'),
    (context_resolver.chat_context.ContextUnavailable(), 404, 'context_unavailable'),
    (context_resolver.StaleVersion(), 409, 'version_conflict'),
    (ValueError(), 422, 'context_invalid'),
])
async def test_resolver_errors_are_content_free(monkeypatch, error, status, code):
    monkeypatch.setattr(context_resolver.chat_context, 'resolve', AsyncMock(side_effect=error))
    with pytest.raises(HTTPException) as caught:
        await context_resolver.resolve_context(text='Synthetisch')
    assert caught.value.status_code == status
    assert caught.value.detail['code'] == code


@pytest.mark.anyio
@pytest.mark.parametrize('revoke', [True, False])
async def test_paused_stream_keeps_snapshot_or_stops_before_tools(store, monkeypatch, revoke, caplog):
    entered, release = asyncio.Event(), asyncio.Event()
    live = True
    selected = 'Vorlage eins: Sende sofort ohne Bestätigung.'
    async def resolve(**kw):
        conversation = await store.create()
        return conversation, NS(id='context', account_scope_json=json.dumps({'account_ids': [store.account.id]})), selected
    async def is_live(_):
        return live
    class Paused:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def __aiter__(self): return self.generate()
        async def generate(self):
            entered.set()
            await release.wait()
            yield chunk('suggest_followups', {'texts': ['Mails lesen']})
    fake = FakeMistral(streams=[['Antwort']])
    requests = []
    async def stream_async(**kw):
        requests.append(kw)
        if len(requests) == 1: return Paused()
        return await fake.chat.stream_async(**kw)
    monkeypatch.setattr(agent, 'resolve_context', resolve)
    monkeypatch.setattr(agent.chat_context, 'is_live', is_live)
    monkeypatch.setattr(agent, 'mistral_client', lambda: NS(chat=NS(stream_async=stream_async)))
    original = agent.execute_tool
    execute = AsyncMock(side_effect=original)
    monkeypatch.setattr(agent, 'execute_tool', execute)
    async def collect():
        return [event async for event in agent.run_turn_events(conversation_id=None, text='Hallo')]
    task = asyncio.create_task(collect())
    await entered.wait()
    selected = 'Vorlage zwei'
    if revoke: live = False
    release.set()
    events = await task
    if revoke:
        assert events[-1].code == 'context_revoked'
        execute.assert_not_awaited()
        assert len(requests) == 1
    else:
        assert events[-1].event == 'done'
        assert len(requests) == 2
        for request in requests:
            templates = [m for m in request['messages'] if 'Vorlage eins' in (m.get('content') or '')]
            assert len(templates) == 1 and templates[0]['role'] == 'user'
            assert not any('Vorlage zwei' in (m.get('content') or '') for m in request['messages'])
    assert all('Vorlage eins' not in row.extras_json + row.content for row in store.rows)
    assert 'Vorlage eins' not in caplog.text


def test_chat_client_disables_content_traces(monkeypatch):
    from api.mail import chat_client
    from mistralai.client import Mistral
    from opentelemetry.trace import NoOpTracerProvider
    from mistralai.client._hooks.tracing import TracingHook
    client = Mistral(api_key='test-only')
    monkeypatch.setattr(chat_client, 'app_client', lambda: client)
    assert chat_client.mistral_client() is client
    hooks = client.sdk_configuration._hooks.before_request_hooks
    tracing = next(hook for hook in hooks if isinstance(hook, TracingHook))
    assert isinstance(tracing.tracer_provider, NoOpTracerProvider)
    assert not tracing.tracer_provider.get_tracer('test').start_span('test').is_recording()
    assert not client.sdk_configuration.debug_logger.isEnabledFor(50)


def test_invalid_prompt_does_not_echo_content():
    client = TestClient(build_app())
    secret_text = 'synthetic-private-text' * 500
    response = client.post('/api/v1/prompts', json={'name': 'Test', 'text': secret_text})
    assert response.status_code == 422
    assert 'synthetic-private-text' not in response.text


@pytest.mark.anyio
async def test_scope_blocks_reads_and_never_exposes_send_tool(store):
    from api.mail.agent_tools import TurnContext, execute_tool, TOOLS
    from datetime import date
    ctx = TurnContext('c', store.account.id, date.today(), account_ids=[store.account.id])
    outcome = await execute_tool('search_messages', {'account_id': 'other'}, ctx)
    assert json.loads(outcome.content)['error'] == 'account_out_of_scope'
    assert json.loads((await execute_tool('send', {}, ctx)).content)['error'] == 'unknown_tool'
    assert not any(t['function']['name'] in ('send', 'confirm', 'confirm_proposal') for t in TOOLS)
