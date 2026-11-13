"""Confirmed sends use connector credentials and expose only safe failure codes."""

import importlib
import json
import smtplib
from unittest.mock import AsyncMock

import pytest
from db.models.chat_message import ChatMessage
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.mail import connectors, service, transport

confirm = importlib.import_module("api.routers.api.v1.chat.drafts.[draft_id].confirm")


@pytest.fixture
async def setup(fake_store, monkeypatch):
    account = await fake_store.create_account(provider="gmail", auth_type=connectors.CONNECTOR, email_address="max@example.org")
    message = ChatMessage(conversation_id="chat", role="draft", draft_json=json.dumps({"status": "pending", "account_id": account.id, "to": ["you@example.org"], "subject": "Hello", "body": "Body"}))
    monkeypatch.setattr(confirm.message_access, "get_message", AsyncMock(return_value=message))
    async def update(draft_id, payload):
        message.draft_json = payload
        return message
    monkeypatch.setattr(confirm.message_access, "update_draft_json", update)
    no_credentials = AsyncMock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(service, "load_credentials", no_credentials)
    monkeypatch.setattr(confirm, "load_credentials", no_credentials, raising=False)
    app = FastAPI()
    app.include_router(confirm.router, prefix="/drafts/{draft_id}/confirm")
    return TestClient(app), message


@pytest.mark.anyio
async def test_confirm_sends_connector_draft_without_credentials(setup, monkeypatch):
    client, message = setup
    send = AsyncMock(return_value="sent")
    monkeypatch.setattr(connectors, "call_write_tool", send, raising=False)
    response = client.post(f"/drafts/{message.id}/confirm")
    assert response.status_code == 200
    assert json.loads(message.draft_json)["status"] == "sent"
    send.assert_awaited_once_with("gmail", "send_email", {"to": ["you@example.org"], "subject": "Hello", "body": "Body"})


@pytest.mark.anyio
@pytest.mark.parametrize("blocked", [True, False])
async def test_confirm_maps_blocked_host_to_host_not_allowed(setup, monkeypatch, blocked):
    client, message = setup
    error = transport.MailHostNotAllowedError("private host") if blocked else smtplib.SMTPException("535 secret-ish provider text")
    monkeypatch.setattr(confirm.send_service, "send_message", AsyncMock(side_effect=error))
    response = client.post(f"/drafts/{message.id}/confirm")
    code = "host_not_allowed" if blocked else "send_failed"
    assert response.status_code == (422 if blocked else 502)
    assert response.json()["detail"]["code"] == code
    draft = json.loads(message.draft_json)
    assert draft["status"] == "failed"
    assert draft["error"] == code
    assert "535" not in response.text + message.draft_json


@pytest.mark.anyio
async def test_confirm_hides_provider_error_text(setup, monkeypatch):
    await test_confirm_maps_blocked_host_to_host_not_allowed(setup, monkeypatch, False)
