"""Connector capability boundaries."""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.mail import connectors
from api.routers.api.v1.mail import connectors as routes


def test_call_tool_route_is_gone():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/mail/connectors")
    assert TestClient(app).post("/api/v1/mail/connectors/gmail/tools/send_email", json={}).status_code in (404, 405)
    assert "mail_connector_call_tool" not in {op["operationId"] for path in app.openapi()["paths"].values() for op in path.values()}


@pytest.mark.anyio
async def test_read_call_refuses_write_tool():
    with pytest.raises(connectors.ToolNotAllowedError):
        await connectors.call_read_tool("gmail", "send_email", {})


@pytest.mark.anyio
async def test_write_call_refuses_unknown_tool():
    with pytest.raises(connectors.ToolNotAllowedError):
        await connectors.call_write_tool("gmail", "delete_label", {})


def test_only_send_and_actions_call_write_tools():
    root = Path(__file__).parents[1] / "src/api"
    allowed = {"mail/connectors.py", "mail/send.py", "mail/actions.py"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        if any(getattr(node, "attr", None) == "call_write_tool" or getattr(node, "id", None) == "call_write_tool" or getattr(node, "name", None) == "call_write_tool" for node in ast.walk(tree)):
            assert path.relative_to(root).as_posix() in allowed


@pytest.mark.anyio
async def test_named_mailbox_is_pinned_for_reads_and_writes(monkeypatch):
    import json
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit
    from unittest.mock import AsyncMock
    from api.mail import connector_mailbox

    mailbox = SimpleNamespace(id='account-a', provider='gmail', email_address='a@example.test')
    thread = {'id': 'sent-thread', 'messages': [{'id': 'sent-message', 'labelIds': ['SENT'], 'sender': 'A <a@example.test>'}]}
    listing = AsyncMock(return_value={'credentials': [{'name': 'credential A/1', 'authentication_type': 'oauth2'}]})
    monkeypatch.setattr(connectors, '_get', listing)
    sent = []
    visible = thread

    async def dispatch(path, payload):
        parsed = urlsplit(path)
        assert parse_qs(parsed.query) == {'credentials_name': ['credential A/1']}
        tool = parsed.path.split('/')[-2]
        if tool == 'search_threads':
            assert payload['arguments']['query'] == 'in:sent from:me'
            result = {'threads': [visible]}
        elif tool == 'get_thread':
            result = visible
        else:
            sent.append(tool)
            result = {}
        return {'content': [{'text': json.dumps(result)}]}

    invalidated = AsyncMock()
    monkeypatch.setattr(connector_mailbox.chat_settings, 'invalidate_connector', invalidated)
    monkeypatch.setattr(connectors, '_post', dispatch)
    async with connector_mailbox.bound_mailbox(mailbox, cursor='234', bootstrap=True, check_after=True) as (binding, progress):
        assert progress == ''
    state = SimpleNamespace(connector_verified=True, cursor=connector_mailbox.encode(binding, '350'))
    monkeypatch.setattr(connector_mailbox.mail_sync_state, 'get_state', AsyncMock(return_value=state))
    listing.return_value = {'credentials': [{'name': 'new-default', 'authentication_type': 'oauth2'}]}
    await connectors.call_write_tool(mailbox, 'send_email', {})
    assert sent == ['send_email']
    assert listing.await_count == 1
    visible = {'id': 'different-thread', 'messages': thread['messages']}
    with pytest.raises(connector_mailbox.MailboxUnavailable):
        await connectors.call_write_tool(mailbox, 'send_email', {})
    assert sent == ['send_email']
    invalidated.assert_awaited_once_with(mailbox.id)
    assert connectors.mailbox_credential.get() is None


@pytest.mark.anyio
async def test_connector_change_during_sync_discards_the_unverified_page(fake_store, monkeypatch):
    from unittest.mock import AsyncMock
    from api.mail import connector_mailbox, sync, sync_connector
    from api.mail.sync_types import SyncChanges
    account = await fake_store.create_account(provider='gmail', auth_type=connectors.CONNECTOR, email_address='a@example.test')
    binding = ('named', 'thread-a', 'message-a')
    await fake_store.save_state(account_id=account.id, cursor=connector_mailbox.encode(binding, '27'), connector_verified=True)
    thread = {'id': 'thread-a', 'messages': [{'id': 'message-a', 'sender': account.email_address, 'labelIds': ['SENT']}]}
    monkeypatch.setattr(connectors, 'call_read_tool_json', AsyncMock(side_effect=[thread, {'id': 'thread-b', 'messages': []}]))
    invalidated = AsyncMock()
    monkeypatch.setattr(connector_mailbox.chat_settings, 'invalidate_connector', invalidated)
    monkeypatch.setattr(sync_connector, 'fetch_changes', AsyncMock(return_value=SyncChanges(cursor='29', full_rebuild=True)))
    replace = AsyncMock()
    monkeypatch.setattr(sync.message_access, 'delete_folder', replace)
    result = await sync.sync_account(account.id)
    assert (result.status, result.error_code) == ('error', 'auth_expired')
    replace.assert_not_awaited()
    invalidated.assert_awaited_once_with(account.id)


@pytest.mark.anyio
@pytest.mark.parametrize('after,status_code', [(False, 429), (True, 503), (True, None)])
async def test_transient_proof_failure_retains_the_mailbox_binding(monkeypatch, after, status_code):
    import httpx
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from api.mail import connector_mailbox
    account = SimpleNamespace(id='account', provider='gmail', email_address='a@example.test')
    thread = {'id': 'thread', 'messages': [{'id': 'message', 'sender': account.email_address, 'labelIds': ['SENT']}]}
    request = httpx.Request('GET', 'https://example.test')
    error = httpx.ReadTimeout('timeout', request=request) if status_code is None else httpx.HTTPStatusError(
        'temporary', request=request, response=httpx.Response(status_code, request=request))
    monkeypatch.setattr(connectors, 'call_read_tool_json', AsyncMock(side_effect=[thread, error] if after else [error]))
    invalidate = AsyncMock()
    monkeypatch.setattr(connector_mailbox.chat_settings, 'invalidate_connector', invalidate)
    with pytest.raises(httpx.HTTPError):
        async with connector_mailbox.bound_mailbox(account, cursor=connector_mailbox.encode(('pinned', 'thread', 'message'), '12'), check_after=True):
            assert after
    invalidate.assert_not_awaited()
    assert connectors.mailbox_credential.get() is None
