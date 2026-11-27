"""Connect and reuse checks with isolated accessors and transports."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.mail import crypto, secrets, sync, transport
from api.routers.api.v1.mail import accounts
from utils.mistral import MistralNotConfiguredError


@pytest.fixture
def setup(monkeypatch, fake_store):
    monkeypatch.setattr(transport, "resolve_public", AsyncMock(return_value=["8.8.8.8"]))
    monkeypatch.setattr(crypto.mail_env, "mail_token_encryption_key", crypto.new_key())
    login = AsyncMock()
    resolve = AsyncMock(return_value="test-password-value")
    monkeypatch.setattr(accounts, "check_imap_login", login)
    monkeypatch.setattr(secrets, "resolve_workspace_secret", resolve)
    app = FastAPI()
    app.include_router(accounts.router, prefix="/accounts")
    return TestClient(app), login, resolve


def test_connect_imap_rejects_foreign_secret(setup):
    client, login, resolve = setup
    response = client.post("/accounts/imap", json={"email_address": "me@yahoo.com", "password_secret": "mistral_api_key"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "secret_not_allowed"
    resolve.assert_not_called()
    login.assert_not_called()


@pytest.mark.parametrize("field", ["imap_host", "smtp_host"])
def test_connect_imap_rejects_unknown_host(setup, field):
    client, login, _ = setup
    response = client.post("/accounts/imap", json={"email_address": "me@yahoo.com", "password_secret": "yahoo-app-password", field: "evil.example"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "host_not_allowed"
    login.assert_not_called()


def test_connect_imap_stores_reference_only(setup, fake_store):
    client, _, _ = setup
    response = client.post("/accounts/imap", json={"email_address": "me@yahoo.com", "password_secret": "Yahoo-App-Password", "imap_use_ssl": False})
    assert response.status_code == 201
    payload = crypto.decrypt_payload(next(iter(fake_store.credentials.values())))
    assert payload["password_secret"] == "yahoo-app-password"
    assert "test-password-value" not in str(payload)
    assert "password" not in payload
    assert "imap_use_ssl" not in payload


def test_connect_fastmail_stores_preset_without_server_overrides(setup, fake_store, monkeypatch):
    client, login, resolve = setup
    monkeypatch.setattr(transport.mail_env, "mail_imap_allowed_hosts", "")

    response = client.post("/accounts/imap", json={
        "email_address": "me@fastmail.com", "password_secret": "fastmail-app-password",
    })

    assert response.status_code == 201
    login.assert_awaited_once_with(
        email_address="me@fastmail.com", password="test-password-value", host="imap.fastmail.com", port=993,
    )
    resolve.assert_awaited_once_with("fastmail-app-password")
    payload = crypto.decrypt_payload(next(iter(fake_store.credentials.values())))
    assert payload == {
        "imap_host": "imap.fastmail.com", "imap_port": 993,
        "smtp_host": "smtp.fastmail.com", "smtp_port": 465, "smtp_starttls": False,
        "password_secret": "fastmail-app-password",
    }


@pytest.mark.anyio
async def test_sync_refuses_stored_host_no_longer_allowed(setup, fake_store, monkeypatch):
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="me@example.org")
    await fake_store.store_credential(account_id=account.id, kind="imap_password", encrypted_payload=crypto.encrypt_payload({"imap_host": "removed.example.org", "password": "test-only"}))
    opener = Mock()
    monkeypatch.setattr(transport, "open_imap", opener)
    result = await sync.sync_account(account.id)
    assert result.status == "error"
    assert result.error_code == "host_not_allowed"
    opener.assert_not_called()


@pytest.mark.parametrize("failure,status,code", [(secrets.WorkspaceSecretNotFoundError("private data"), 404, "secret_not_found"), (OSError("private data"), 502, "login_failed")])
def test_connect_errors_are_safe(setup, failure, status, code):
    client, login, resolve = setup
    if status == 404:
        resolve.side_effect = failure
    else:
        login.side_effect = failure
    response = client.post("/accounts/imap", json={"email_address": "me@yahoo.com", "password_secret": "yahoo-app-password"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "private data" not in response.text


@pytest.mark.parametrize("failure,status,code", [
    (MistralNotConfiguredError("private data"), 503, "mistral_not_configured"),
    (secrets.WorkspaceSecretAccessDeniedError("private data"), 503, "secret_access_denied"),
    (httpx.ConnectError("private data"), 502, "secret_unavailable"),
])
def test_connect_explains_why_the_secret_is_unreadable(setup, fake_store, failure, status, code):
    client, login, resolve = setup
    resolve.side_effect = failure
    response = client.post("/accounts/imap", json={"email_address": "me@yahoo.com", "password_secret": "yahoo-app-password"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "private data" not in response.text
    login.assert_not_called()
    assert not fake_store.accounts


def test_connect_without_encryption_key_creates_no_account(setup, fake_store, monkeypatch):
    client, _, _ = setup
    monkeypatch.setattr(crypto.mail_env, "mail_token_encryption_key", None)
    response = client.post("/accounts/imap", json={"email_address": "me@yahoo.com", "password_secret": "yahoo-app-password"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "encryption_not_configured"
    assert not fake_store.accounts
    assert not fake_store.credentials
