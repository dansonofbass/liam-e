"""Model catalogue contracts."""
from types import SimpleNamespace as NS

import pytest
from support.fake_mistral import FakeMistral

pytestmark = pytest.mark.anyio


async def test_models_list_keeps_function_calling_models_with_german_labels(monkeypatch):
    from api.mail import models_catalog as catalog
    card = NS(id='mistral-medium-2508', aliases=['mistral-medium-latest'], capabilities=NS(completion_chat=True, function_calling=True), deprecation=None)
    bad = NS(id='bad', aliases=[], capabilities=NS(completion_chat=True, function_calling=False), deprecation=None)
    fake = FakeMistral(models=[NS(data=[card, bad])])
    monkeypatch.setattr(catalog, 'mistral_client', lambda: fake)
    catalog.reset_cache()
    models = await catalog.list_chat_models()
    assert any(m.id == 'mistral-medium-latest' and m.label == 'Mistral Medium' and m.description for m in models)
    assert not any(m.id == 'bad' for m in models)


async def test_model_catalog_cache_and_deprecation(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from api.mail import models_catalog as catalog
    old = NS(id='retired', aliases=[], capabilities=NS(completion_chat=True, function_calling=True), deprecation=datetime.now(timezone.utc) - timedelta(hours=1))
    fake = FakeMistral(models=[NS(data=[old])])
    monkeypatch.setattr(catalog, 'mistral_client', lambda: fake)
    catalog.reset_cache()
    first = await catalog.list_chat_models()
    second = await catalog.list_chat_models()
    assert not any(m.id == 'retired' for m in first)
    assert first == second and len(fake.requests) == 1


async def test_patch_model_and_title(monkeypatch):
    from db.models.chat_conversation import ChatConversation
    from api.routers.api.v1.chat import conversations
    from api.mail.models_catalog import ChatModelOut
    row = ChatConversation(title='Alt', model='old')
    async def get(id): return row if id == row.id else None
    async def update(id, expected_version, *, model=None, title=None, **kw):
        if model is not None: row.model = model
        if title is not None: row.title = title
        return row
    async def models(): return [ChatModelOut(id='valid', label='Valid', description='', is_default=False)]
    monkeypatch.setattr(conversations.conversation_access, 'get_conversation', get)
    monkeypatch.setattr(conversations.chat_context, 'configure', update)
    monkeypatch.setattr(conversations, 'list_chat_models', models)
    updated = await conversations.update_conversation(row.id, conversations.ChatConversationUpdateIn(expected_version=1, model='valid', title='  Neu  '))
    assert (updated.model, updated.title) == ('valid', 'Neu')
    updated = await conversations.update_conversation(row.id, conversations.ChatConversationUpdateIn(expected_version=1, model=None))
    assert (updated.model, updated.title) == ('', 'Neu')
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await conversations.update_conversation(row.id, conversations.ChatConversationUpdateIn(expected_version=1, model='unknown'))
    assert exc.value.status_code == 422 and exc.value.detail['code'] == 'model_unknown'
    with pytest.raises(HTTPException) as exc:
        await conversations.update_conversation(row.id, conversations.ChatConversationUpdateIn(expected_version=1, model=''))
    assert exc.value.detail['code'] == 'model_unknown'


async def test_models_list_falls_back_to_default_on_api_error(monkeypatch):
    from api.mail import models_catalog as catalog
    fake = FakeMistral(models=[RuntimeError('offline')])
    monkeypatch.setattr(catalog, 'mistral_client', lambda: fake)
    catalog.reset_cache()
    models = await catalog.list_chat_models()
    assert len(models) == 1 and models[0].is_default
