"""Connector identity must come from sent mail and never replace another connection."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.mail import connectors, service
from api.routers.api.v1.mail import accounts
from api.routers.api.v1.mail import connectors as routes


@pytest.fixture
def setup(monkeypatch, fake_store):
    monkeypatch.setattr(connectors, "list_tools", AsyncMock(return_value=[{"name": "search_threads"}]))
    app = FastAPI()
    app.include_router(routes.router, prefix="/connectors")
    return TestClient(app)


def fake_search(monkeypatch, messages):
    async def search(connector, tool, arguments):
        assert arguments == {"query": "in:sent", "pageSize": 1}
        return {"threads": [{"messages": messages}]}
    monkeypatch.setattr(connectors, "call_read_tool_json", search, raising=False)


@pytest.mark.parametrize("sender", ["max@example.org", "Max <MAX@example.org>"])
def test_connect_connector_takes_address_from_sent_mail(setup, monkeypatch, sender):
    fake_search(monkeypatch, [{"sender": sender, "labelIds": ["SENT"]}])
    response = setup.post("/connectors/gmail/connect")
    assert response.status_code == 201
    assert response.json()["email_address"] == "max@example.org"


@pytest.mark.parametrize("sender", ["", "not-an-address", "broken@"])
def test_connect_connector_ignores_inbox_recipients(setup, monkeypatch, sender):
    fake_search(monkeypatch, [{"sender": sender, "labelIds": ["SENT"], "toRecipients": ["liste@example.net"]}])
    assert setup.post("/connectors/gmail/connect").json()["email_address"] == "gmail@connector.mistral"


def test_connect_connector_uses_latest_sent_message(setup, monkeypatch):
    fake_search(monkeypatch, [
        {"sender": "older@example.org", "labelIds": ["SENT"], "date": "2026-11-13T12:00:00+02:00"},
        {"sender": "max@example.org", "labelIds": ["SENT"], "date": "2026-11-13T11:30:00+00:00"},
    ])
    assert setup.post("/connectors/gmail/connect").json()["email_address"] == "max@example.org"


@pytest.mark.anyio
async def test_upsert_refuses_to_switch_connection_of_existing_account(setup, monkeypatch, fake_store):
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="max@example.org")
    await fake_store.store_credential(account_id=account.id, kind="imap_password", encrypted_payload="unchanged")
    fake_search(monkeypatch, [{"sender": "max@example.org", "labelIds": ["SENT"]}])
    response = setup.post("/connectors/gmail/connect")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_exists"
    assert (account.provider, account.auth_type) == ("imap", "imap_password")
    assert fake_store.credentials[(account.id, "imap_password")] == "unchanged"
    with pytest.raises(service.AccountConflictError):
        await service.upsert_account(provider="imap", auth_type="oauth2", email_address=account.email_address)
    assert await service.upsert_account(provider="imap", auth_type="imap_password", email_address=account.email_address) is account


@pytest.mark.anyio
async def test_conflict_detection_ignores_address_case(setup, monkeypatch, fake_store):
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="Max@example.org")
    await fake_store.store_credential(account_id=account.id, kind="imap_password", encrypted_payload="unchanged")
    before = account.model_dump()
    fake_search(monkeypatch, [{"sender": "max@example.org", "labelIds": ["SENT"]}])
    response = setup.post("/connectors/gmail/connect")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_exists"
    assert account.model_dump() == before
    assert fake_store.credentials == {(account.id, "imap_password"): "unchanged"}
    assert list(fake_store.accounts) == [account.id]


@pytest.mark.anyio
async def test_reconnect_same_connection_ignores_address_case(account_client, fake_store, monkeypatch):
    monkeypatch.setattr(accounts.crypto, "encrypt_payload", lambda payload: "encrypted-test-credential")
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="Max@example.org")
    monkeypatch.setattr(accounts.transport, "check_mail_host", AsyncMock())
    monkeypatch.setattr(accounts, "check_imap_login", AsyncMock())
    response = account_client.post("/accounts/imap", json={
        "email_address": "max@example.org",
        "password": "test-only",
        "imap_host": "imap.example.org",
        "smtp_host": "smtp.example.org",
    })
    assert response.status_code == 201
    assert response.json()["id"] == account.id
    assert list(fake_store.accounts) == [account.id]
    assert account.email_address == "Max@example.org"
    assert response.json()["email_address"] == "Max@example.org"


def test_connect_connector_ignores_inbound_reply_in_sent_thread(setup, monkeypatch):
    fake_search(monkeypatch, [
        {"sender": "max@example.org", "labelIds": ["SENT"], "date": "2026-11-13T10:00:00+00:00"},
        {"sender": "Erika <erika@example.net>", "labelIds": ["INBOX", "UNREAD"], "date": "2026-11-13T11:00:00+00:00"},
    ])
    assert setup.post("/connectors/gmail/connect").json()["email_address"] == "max@example.org"


def test_connect_connector_without_sent_label_uses_placeholder(setup, monkeypatch):
    fake_search(monkeypatch, [
        {"sender": "Erika <erika@example.net>", "labelIds": ["INBOX", "UNREAD"]},
    ])
    assert setup.post("/connectors/gmail/connect").json()["email_address"] == "gmail@connector.mistral"


@pytest.fixture
def account_client():
    app = FastAPI()
    app.include_router(accounts.router, prefix="/accounts")
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.anyio
async def test_imap_connect_refuses_address_of_connector_account(account_client, fake_store, monkeypatch):
    account = await fake_store.create_account(provider="gmail", auth_type=connectors.CONNECTOR, email_address="max@example.org")
    before = account.model_dump()
    monkeypatch.setattr(accounts.transport, "check_mail_host", AsyncMock())
    monkeypatch.setattr(accounts, "check_imap_login", AsyncMock())
    response = account_client.post("/accounts/imap", json={
        "email_address": account.email_address,
        "password": "test-only",
        "imap_host": "imap.example.org",
        "smtp_host": "smtp.example.org",
    })
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "account_exists",
        "message": "Diese Adresse ist schon über einen anderen Weg verbunden. Entferne das Konto zuerst, wenn du die Verbindung wechseln willst.",
    }
    assert account.model_dump() == before
    assert fake_store.credentials == {}
    assert list(fake_store.accounts) == [account.id]


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_oauth_callback_refuses_address_of_imap_account(account_client, fake_store, monkeypatch, provider):
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="max@example.org")
    await fake_store.store_credential(account_id=account.id, kind="imap_password", encrypted_payload="unchanged")
    before = account.model_dump()
    monkeypatch.setattr(accounts.providers, "verify_state", lambda state: {"provider": provider, "redirect_uri": "https://example.org/callback"})
    monkeypatch.setattr(accounts.providers, "exchange_code", AsyncMock(return_value={"access_token": "test-only"}))
    monkeypatch.setattr(accounts.providers, "fetch_account_email", AsyncMock(return_value=account.email_address))
    response = account_client.get(f"/accounts/oauth/{provider}/callback", params={"code": "code", "state": "state"})
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "account_exists",
        "message": "Diese Adresse ist schon über einen anderen Weg verbunden. Entferne das Konto zuerst, wenn du die Verbindung wechseln willst.",
    }
    assert account.model_dump() == before
    assert fake_store.credentials == {(account.id, "imap_password"): "unchanged"}
    assert list(fake_store.accounts) == [account.id]
