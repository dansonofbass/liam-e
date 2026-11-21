"""Owner default chat model settings and resolution contracts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.mail import agent, context_resolver, models_catalog as catalog
from api.routers.api.v1.chat import stream
from conftest import build_app
from db.accessors import chat_model_settings
from db.accessors.prompt_template import StaleVersion
from db.models.chat_model_settings import ChatModelSettings
from support.fake_mistral import FakeMistral


def _card(model_id: str, *aliases: str, completion_chat: bool = True, function_calling: bool = True, deprecation=None):
    return NS(
        id=model_id,
        aliases=list(aliases),
        capabilities=NS(completion_chat=completion_chat, function_calling=function_calling),
        deprecation=deprecation,
    )


def _client_with_store(monkeypatch, initial: ChatModelSettings | None = None):
    stored = initial or ChatModelSettings()

    async def get():
        return ChatModelSettings(owner_scope=stored.owner_scope, default_model=stored.default_model, version=stored.version)

    async def update(expected_version: int, default_model: str | None):
        nonlocal stored
        if stored.version != expected_version:
            raise StaleVersion
        if stored.default_model != default_model:
            stored = ChatModelSettings(owner_scope=stored.owner_scope, default_model=default_model, version=stored.version + 1)
        return await get()

    monkeypatch.setattr(chat_model_settings, 'get', get)
    monkeypatch.setattr(chat_model_settings, 'update', update)
    return TestClient(build_app())


def test_default_model_settings_initial_state_needs_no_catalog_call(monkeypatch):
    def unexpected_catalog():
        raise AssertionError('catalog should not be fetched when default_model is unset')

    monkeypatch.setattr(catalog, 'mistral_client', unexpected_catalog)
    monkeypatch.setattr(catalog.mail_env, 'mail_chat_model', 'mistral-medium-latest')
    catalog.reset_cache()
    client = _client_with_store(monkeypatch)
    res = client.get('/api/v1/settings/chat/model')
    assert res.status_code == 200
    assert res.json() == {
        'version': 1,
        'default_model': None,
        'effective_default_model': 'mistral-medium-latest',
        'app_default_model': 'mistral-medium-latest',
        'status': 'app_default',
    }


def test_setting_validating_updating_and_resetting_default_model(monkeypatch):
    fake = FakeMistral(models=[NS(data=[
        _card('mistral-medium-3-5', 'mistral-medium-latest'),
        _card('mistral-small-2603', 'mistral-small-latest'),
        _card('no-tools', function_calling=False),
        _card('expired', deprecation=datetime.now(timezone.utc) - timedelta(hours=1)),
    ])])
    monkeypatch.setattr(catalog, 'mistral_client', lambda: fake)
    monkeypatch.setattr(catalog.mail_env, 'mail_chat_model', 'mistral-medium-latest')
    catalog.reset_cache()
    client = _client_with_store(monkeypatch)

    for bad in ('missing-model', 'no-tools', 'expired', '', '   '):
        rejected = client.patch('/api/v1/settings/chat/model', json={'expected_version': 1, 'default_model': bad})
        assert rejected.status_code == 422
        assert rejected.json()['detail']['code'] == 'model_unknown'

    extra = client.patch('/api/v1/settings/chat/model', json={'expected_version': 1, 'default_model': None, 'extra': 1})
    assert extra.status_code == 422
    assert extra.json()['detail']['code'] == 'chat_model_settings_invalid'

    saved = client.patch('/api/v1/settings/chat/model', json={'expected_version': 1, 'default_model': 'mistral-small-latest'})
    assert saved.status_code == 200
    assert saved.json() == {
        'version': 2,
        'default_model': 'mistral-small-latest',
        'effective_default_model': 'mistral-small-latest',
        'app_default_model': 'mistral-medium-latest',
        'status': 'available',
    }

    catalogue = {m['id']: m for m in client.get('/api/v1/chat/models').json()}
    assert catalogue['mistral-small-latest']['is_default'] is True
    assert catalogue['mistral-small-latest']['is_app_default'] is False
    assert catalogue['mistral-medium-latest']['is_default'] is False
    assert catalogue['mistral-medium-latest']['is_app_default'] is True

    concrete = client.patch('/api/v1/settings/chat/model', json={'expected_version': 2, 'default_model': 'mistral-small-2603'})
    assert concrete.status_code == 200
    assert concrete.json()['status'] == 'available'
    assert concrete.json()['version'] == 3

    stale = client.patch('/api/v1/settings/chat/model', json={'expected_version': 2, 'default_model': None})
    assert stale.status_code == 409
    assert stale.json()['detail']['code'] == 'version_conflict'

    # Reset works even when the workspace catalog is unreachable.
    monkeypatch.setattr(catalog, '_cached_at', float('-inf'))
    monkeypatch.setattr(catalog, 'mistral_client', lambda: FakeMistral(models=[RuntimeError('offline')]))
    reset = client.patch('/api/v1/settings/chat/model', json={'expected_version': 3, 'default_model': None})
    assert reset.status_code == 200
    assert reset.json() == {
        'version': 4,
        'default_model': None,
        'effective_default_model': 'mistral-medium-latest',
        'app_default_model': 'mistral-medium-latest',
        'status': 'app_default',
    }


def test_catalog_outage_vs_empty_and_removal_semantics(monkeypatch):
    client = _client_with_store(monkeypatch, ChatModelSettings(default_model='mistral-small-latest', version=2))
    monkeypatch.setattr(catalog.mail_env, 'mail_chat_model', 'mistral-medium-latest')

    # Temporary outage keeps the stored preference as effective and refuses new writes.
    monkeypatch.setattr(catalog, 'mistral_client', lambda: FakeMistral(models=[RuntimeError('offline')]))
    catalog.reset_cache()
    outage_write = client.patch('/api/v1/settings/chat/model', json={'expected_version': 2, 'default_model': 'mistral-medium-latest'})
    assert outage_write.status_code == 503
    assert outage_write.json()['detail']['code'] == 'model_catalog_unavailable'
    assert client.get('/api/v1/settings/chat/model').json() == {
        'version': 2,
        'default_model': 'mistral-small-latest',
        'effective_default_model': 'mistral-small-latest',
        'app_default_model': 'mistral-medium-latest',
        'status': 'unverified',
    }
    offline_models = {m['id']: m for m in client.get('/api/v1/chat/models').json()}
    assert offline_models['mistral-small-latest']['is_default'] is True
    assert offline_models['mistral-small-latest']['availability'] == 'unverified'

    # Verified removal falls back to app_default on effective_default_model and /chat/models.
    monkeypatch.setattr(catalog, '_cached_at', float('-inf'))
    monkeypatch.setattr(catalog, 'mistral_client', lambda: FakeMistral(models=[NS(data=[_card('mistral-medium-3-5', 'mistral-medium-latest')])]))
    removed = client.get('/api/v1/settings/chat/model').json()
    assert removed == {
        'version': 2,
        'default_model': 'mistral-small-latest',
        'effective_default_model': 'mistral-medium-latest',
        'app_default_model': 'mistral-medium-latest',
        'status': 'unlisted',
    }
    models = {m['id']: m for m in client.get('/api/v1/chat/models').json()}
    assert models['mistral-medium-latest']['is_default'] is True
    assert models['mistral-medium-latest']['is_app_default'] is True
    assert 'mistral-small-latest' not in models

    # Verified empty catalog also rejects setting any model while allowing reset.
    monkeypatch.setattr(catalog, '_cached_at', float('-inf'))
    monkeypatch.setattr(catalog, 'mistral_client', lambda: FakeMistral(models=[NS(data=[])]))
    empty_set = client.patch('/api/v1/settings/chat/model', json={'expected_version': 2, 'default_model': 'mistral-medium-latest'})
    assert empty_set.status_code == 422
    assert empty_set.json()['detail']['code'] == 'model_unknown'
    assert client.get('/api/v1/settings/chat/model').json()['status'] == 'unlisted'
    assert client.patch('/api/v1/settings/chat/model', json={'expected_version': 2, 'default_model': None}).status_code == 200


@pytest.mark.anyio
async def test_json_and_sse_entry_paths_inherit_default_only_for_new_chats_without_model(monkeypatch):
    resolved_calls = []

    async def fake_resolve(**kwargs):
        resolved_calls.append(kwargs)
        model = kwargs.get('model') or ''
        return NS(id='conv-1', model=model), NS(id='ctx-1', account_scope_json='{"account_ids":[]}'), None

    monkeypatch.setattr(context_resolver.chat_context, 'resolve', fake_resolve)
    monkeypatch.setattr(catalog, 'mistral_client', lambda: FakeMistral(models=[NS(data=[
        _card('mistral-medium-3-5', 'mistral-medium-latest'),
        _card('mistral-small-2603', 'mistral-small-latest'),
        _card('mistral-large-4', 'mistral-large-latest'),
    ])]))
    catalog.reset_cache()
    monkeypatch.setattr(chat_model_settings, 'get', AsyncMock(return_value=ChatModelSettings(default_model='mistral-small-latest', version=2)))

    # New conversation via context_resolver inherits configured default.
    conv, _, _ = await context_resolver.resolve_context(conversation_id=None, text='Hallo')
    assert conv.model == 'mistral-small-latest'
    assert resolved_calls[-1]['model'] == 'mistral-small-latest'

    # Explicit override wins over configured default.
    conv_override, _, _ = await context_resolver.resolve_context(conversation_id=None, text='Hallo', model='mistral-large-latest')
    assert conv_override.model == 'mistral-large-latest'

    # Existing conversation never re-applies default setting.
    await context_resolver.resolve_context(conversation_id='existing-1', text='Weiter', model=None)
    assert resolved_calls[-1]['model'] is None

    # Unlisted default falls back to mail_env.mail_chat_model.
    monkeypatch.setattr(catalog, '_cached_at', float('-inf'))
    monkeypatch.setattr(catalog, 'mistral_client', lambda: FakeMistral(models=[NS(data=[_card('mistral-medium-3-5', 'mistral-medium-latest')])]))
    monkeypatch.setattr(catalog.mail_env, 'mail_chat_model', 'mistral-medium-latest')
    fallback_conv, _, _ = await context_resolver.resolve_context(conversation_id=None, text='Fallback')
    assert fallback_conv.model == 'mistral-medium-latest'

    # Verify both /chat (JSON) and /chat/stream (SSE) reach resolve_context identically.
    captured_models = []

    async def fake_turn(*, conversation_id=None, text='', model=None, resolved_context=None, **kwargs):
        ctx_conv, ctx_snap, ctx_prompt = resolved_context if resolved_context is not None else await context_resolver.resolve_context(conversation_id=conversation_id, text=text, model=model, **kwargs)
        captured_models.append(ctx_conv.model)
        yield agent.StartEvent(conversation_id=ctx_conv.id, user_message_id='u1', model=ctx_conv.model)
        yield agent.DoneEvent(conversation_id=ctx_conv.id, message_id='a1', stopped=False)

    monkeypatch.setattr(catalog, '_cached_at', float('-inf'))
    monkeypatch.setattr(catalog, 'mistral_client', lambda: FakeMistral(models=[NS(data=[
        _card('mistral-medium-3-5', 'mistral-medium-latest'),
        _card('mistral-small-2603', 'mistral-small-latest'),
    ])]))
    monkeypatch.setattr(agent, 'run_turn_events', fake_turn)
    monkeypatch.setattr(stream, 'run_turn_events', fake_turn)
    monkeypatch.setattr(agent.message_access, 'list_messages', AsyncMock(return_value=[]))

    app = TestClient(build_app())
    json_res = app.post('/api/v1/chat', json={'message': 'Hallo'})
    assert json_res.status_code == 200
    with app.stream('POST', '/api/v1/chat/stream', json={'text': 'Hallo'}) as sse_res:
        assert sse_res.status_code == 200
        list(sse_res.iter_lines())
    assert captured_models == ['mistral-small-latest', 'mistral-small-latest']
