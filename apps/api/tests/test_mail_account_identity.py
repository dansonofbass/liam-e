"""Connector identity must come from sent mail and never replace another connection."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.mail import connectors, service
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
    fake_search(monkeypatch, [{"sender": sender}])
    response = setup.post("/connectors/gmail/connect")
    assert response.status_code == 201
    assert response.json()["email_address"] == "max@example.org"


@pytest.mark.parametrize("sender", ["", "not-an-address", "broken@"])
def test_connect_connector_ignores_inbox_recipients(setup, monkeypatch, sender):
    fake_search(monkeypatch, [{"sender": sender, "toRecipients": ["liste@example.net"]}])
    assert setup.post("/connectors/gmail/connect").json()["email_address"] == "gmail@connector.mistral"


def test_connect_connector_uses_latest_sent_message(setup, monkeypatch):
    fake_search(monkeypatch, [
        {"sender": "older@example.org", "date": "2026-11-13T12:00:00+02:00"},
        {"sender": "max@example.org", "date": "2026-11-13T11:30:00+00:00"},
    ])
    assert setup.post("/connectors/gmail/connect").json()["email_address"] == "max@example.org"


@pytest.mark.anyio
async def test_upsert_refuses_to_switch_connection_of_existing_account(setup, monkeypatch, fake_store):
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="max@example.org")
    await fake_store.store_credential(account_id=account.id, kind="imap_password", encrypted_payload="unchanged")
    fake_search(monkeypatch, [{"sender": "max@example.org"}])
    response = setup.post("/connectors/gmail/connect")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_exists"
    assert (account.provider, account.auth_type) == ("imap", "imap_password")
    assert fake_store.credentials[(account.id, "imap_password")] == "unchanged"
    with pytest.raises(service.AccountConflictError):
        await service.upsert_account(provider="imap", auth_type="oauth2", email_address=account.email_address)
    assert await service.upsert_account(provider="imap", auth_type="imap_password", email_address=account.email_address) is account
