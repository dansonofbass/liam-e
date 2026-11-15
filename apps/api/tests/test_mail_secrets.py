"""Account secrets cannot select application credentials."""

import httpx
import pytest
from unittest.mock import Mock

from api.mail import secrets


def answer_with(monkeypatch, status, body=()):
    """Serve every secrets request with one fixed response, without network or a real credential."""
    monkeypatch.setattr(secrets, "mistral_app_token", lambda: "test-token")
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=list(body)))
    client = httpx.AsyncClient
    monkeypatch.setattr(secrets.httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))


def test_validate_secret_name():
    assert secrets.validate_secret_name("Yahoo-App-Password") == "yahoo-app-password"


@pytest.mark.parametrize("name", ["mail_token_encryption_key", "mistral_api_key", "", "../x-app-password", "foo-app-password-x"])
def test_validate_secret_name_rejects(name):
    with pytest.raises(secrets.SecretNameNotAllowedError):
        secrets.validate_secret_name(name)


def test_app_secret_names():
    assert "mail_token_encryption_key" in secrets.app_secret_names()


def test_reserved_matching_name(monkeypatch):
    monkeypatch.setattr(secrets, "app_secret_names", lambda: frozenset({"reserved-app-password"}))
    with pytest.raises(secrets.SecretNameNotAllowedError):
        secrets.validate_secret_name("reserved-app-password")


@pytest.mark.anyio
async def test_resolution_validates_before_http(monkeypatch):
    client = Mock()
    monkeypatch.setattr(secrets.httpx, "AsyncClient", client)
    with pytest.raises(secrets.SecretNameNotAllowedError):
        await secrets.resolve_workspace_secret("mistral_api_key")
    client.assert_not_called()


@pytest.mark.anyio
async def test_resolution_returns_the_named_value(monkeypatch):
    answer_with(monkeypatch, 200, [{"name": "secret:workspace:yahoo-app-password", "value": "test-value"}])
    assert await secrets.resolve_workspace_secret("yahoo-app-password") == "test-value"


@pytest.mark.anyio
async def test_missing_secret_is_not_found(monkeypatch):
    answer_with(monkeypatch, 404)
    with pytest.raises(secrets.WorkspaceSecretNotFoundError):
        await secrets.resolve_workspace_secret("yahoo-app-password")


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403])
async def test_refused_credential_is_not_a_missing_secret(monkeypatch, status):
    answer_with(monkeypatch, status)
    with pytest.raises(secrets.WorkspaceSecretAccessDeniedError):
        await secrets.resolve_workspace_secret("yahoo-app-password")
