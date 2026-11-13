"""Account secrets cannot select application credentials."""

import pytest
from unittest.mock import Mock

from api.mail import secrets


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
