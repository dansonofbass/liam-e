"""Transport policy tests; no sockets are opened."""

import ssl
from unittest.mock import AsyncMock, Mock

import pytest

from api.mail import netguard, secrets, send, service, sync, transport
from db.models.mail_account import MailAccount


@pytest.mark.anyio
async def test_smtp_checks_host_before_password_or_worker(monkeypatch):
    password = AsyncMock()
    worker = Mock()
    monkeypatch.setattr(service, "imap_password", password)
    monkeypatch.setattr(send, "_send_smtp", worker)
    account = MailAccount(provider="imap", auth_type="imap_password", email_address="me@example.org")
    with pytest.raises(transport.MailHostNotAllowedError):
        await send.send_message(account, credentials={"smtp_host": "evil.example"}, to=["to@example.org"], subject="Test", body="Test")
    password.assert_not_called()
    worker.assert_not_called()


@pytest.mark.anyio
async def test_sync_ignores_stored_false(monkeypatch, fake_store):
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="me@gmail.com")
    monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={"imap_host": "imap.gmail.com", "imap_use_ssl": False, "password": "test-only"}))
    monkeypatch.setattr(transport, "resolve_public", AsyncMock(return_value=["8.8.8.8"]))
    connection = Mock()
    connection.select.return_value = ("OK", [b"0"])
    connection.response.return_value = ("UIDVALIDITY", [b"7"])
    connection.uid.return_value = ("OK", [b""])
    monkeypatch.setattr(sync.message_access, "known_uids", AsyncMock(return_value={}))
    monkeypatch.setattr(sync.message_access, "delete_folder", AsyncMock(return_value=0))
    opener = Mock(return_value=connection)
    monkeypatch.setattr(transport, "open_imap", opener)
    assert (await sync.sync_account(account.id)).status == "ok"
    opener.assert_called_once_with("imap.gmail.com", 993)

    connection.select.return_value = ("NO", [])
    result = await sync.sync_account(account.id)
    assert result.status == "error"
    assert result.error_code == "provider_error"


@pytest.mark.anyio
async def test_sync_stores_missing_workspace_secret(monkeypatch, fake_store):
    account = await fake_store.create_account(provider="imap", auth_type="imap_password", email_address="me@gmail.com")
    monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={"imap_host": "imap.gmail.com", "password_secret": "gmail-app-password"}))
    monkeypatch.setattr(service, "imap_password", AsyncMock(side_effect=secrets.WorkspaceSecretNotFoundError("missing")))
    result = await sync.sync_account(account.id)
    assert result.error_code == "secret_not_found"
    state = await sync.sync_state_access.get_state(account.id)
    assert state.last_error == "secret_not_found"


def test_starttls_failure_closes_connection(monkeypatch):
    server = Mock()
    server.starttls.side_effect = ssl.SSLError("test")
    monkeypatch.setattr(transport.smtplib, "SMTP", Mock(return_value=server))
    with pytest.raises(ssl.SSLError):
        transport.open_smtp("smtp.gmail.com", 587, starttls=True)
    server.close.assert_called_once()
    server.login.assert_not_called()


def test_tls_context_verifies():
    context = transport.tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_open_imap_uses_verified_context(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(transport.imaplib, "IMAP4_SSL", constructor)
    transport.open_imap("imap.gmail.com", 993)
    assert constructor.call_args.kwargs["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    assert constructor.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("starttls", [True, False])
def test_open_smtp_starttls_uses_verified_context(monkeypatch, starttls):
    constructor = Mock()
    monkeypatch.setattr(transport.smtplib, "SMTP" if starttls else "SMTP_SSL", constructor)
    transport.open_smtp("smtp.gmail.com", 587 if starttls else 465, starttls=starttls)
    call = constructor.return_value.starttls.call_args if starttls else constructor.call_args
    assert call.kwargs["context"].verify_mode == ssl.CERT_REQUIRED
    assert call.kwargs["context"].check_hostname


@pytest.mark.anyio
async def test_check_mail_host_rejects_unknown_host(monkeypatch):
    resolver = AsyncMock()
    monkeypatch.setattr(transport, "resolve_public", resolver)
    with pytest.raises(transport.MailHostNotAllowedError):
        await transport.check_mail_host("evil.example")
    resolver.assert_not_called()


@pytest.mark.anyio
async def test_check_mail_host_accepts_allowlisted_env_host(monkeypatch):
    monkeypatch.setattr(transport.mail_env, "mail_imap_allowed_hosts", " MAIL.EXAMPLE.ORG, ")
    resolver = AsyncMock(return_value=["8.8.8.8"])
    monkeypatch.setattr(transport, "resolve_public", resolver)
    await transport.check_mail_host("mail.example.org")
    resolver.assert_awaited_once_with("mail.example.org")


@pytest.mark.anyio
async def test_check_mail_host_rejects_allowlisted_host_resolving_private(monkeypatch):
    monkeypatch.setattr(transport, "resolve_public", AsyncMock(side_effect=netguard.BlockedAddressError()))
    with pytest.raises(netguard.BlockedAddressError):
        await transport.check_mail_host("imap.gmail.com")
