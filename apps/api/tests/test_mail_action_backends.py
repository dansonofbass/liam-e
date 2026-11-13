"""Provider wire contracts use invented message identifiers only."""

import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from db.models.mail_account import MailAccount
from db.models.mail_message import MailMessage

from api.mail import action_backends as backends, connectors, service, transport
from api.mail.actions import ActionUnsupportedError


def account(provider="imap", auth_type="imap_password"):
    return MailAccount(id="a", provider=provider, auth_type=auth_type, email_address="ada@example.test")


def message(**kwargs):
    return MailMessage(id="m", account_id="a", provider_uid="12", rfc_message_id="<invented@example.test>", **kwargs)


@pytest.fixture
def imap(monkeypatch):
    connection = Mock()
    connection.capabilities = (b"IMAP4rev1", b"MOVE", b"UIDPLUS")
    connection.login.return_value = ("OK", [])
    connection.select.return_value = ("OK", [])
    connection.list.return_value = ("OK", [b'(\\HasNoChildren \\Archive) "/" "Archiv"', b'(\\Trash) "/" "Bin"'])
    connection.uid.side_effect = lambda command, *args: ("OK", [b"91"] if command.upper() == "SEARCH" else [])
    connection.response.return_value = ("COPYUID", [b"1 12 91"])
    monkeypatch.setattr(transport, "open_imap", Mock(return_value=connection))
    monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
    monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={"imap_host": "imap.example.test"}))
    monkeypatch.setattr(service, "imap_password", AsyncMock(return_value=""))
    return connection


@pytest.mark.anyio
async def test_imap_backend_prefers_special_use_folder(imap):
    result = await backends.backend_for(account()).apply(message(), "archive")
    imap.list.assert_called_once_with('""', '"*"')
    assert any(call.args == ("MOVE", "12", '"Archiv"') for call in imap.uid.call_args_list)
    assert result["provider_uid"] == "91"


@pytest.mark.anyio
async def test_imap_backend_falls_back_to_copy_and_delete_without_move(imap):
    imap.capabilities = (b"IMAP4rev1", b"UIDPLUS")
    await backends.backend_for(account()).apply(message(), "archive")
    assert [call.args for call in imap.uid.call_args_list] == [
        ("COPY", "12", '"Archiv"'), ("STORE", "12", "+FLAGS", "(\\Deleted)"), ("EXPUNGE", "12")]


@pytest.mark.anyio
async def test_imap_undo_finds_message_by_message_id(imap):
    previous = {"folder": "INBOX", "is_read": False, "provider_uid": "12", "labels_json": "[]"}
    result = await backends.backend_for(account()).revert(message(folder="ARCHIVE"), previous)
    imap.uid.assert_any_call("SEARCH", None, "HEADER", "Message-ID", '"<invented@example.test>"')
    imap.uid.assert_any_call("MOVE", "91", '"INBOX"')
    assert result["provider_uid"] == "91"


@pytest.mark.anyio
async def test_imap_restore_searches_inbox_when_copyuid_missing(imap):
    imap.response.return_value = (None, [None])
    result = await backends.backend_for(account()).apply(message(folder="ARCHIVE"), "restore")
    imap.select.assert_any_call('"INBOX"')
    assert result["provider_uid"] == "91"


@pytest.mark.anyio
async def test_imap_read_and_folder_fallback(imap):
    imap.list.return_value = ("OK", [b'() "/" "Archive"'])
    backend = backends.backend_for(account())
    await backend.apply(message(), "mark_read")
    imap.uid.assert_any_call("STORE", "12", "+FLAGS", "(\\Seen)")
    await backend.apply(message(), "archive")
    imap.uid.assert_any_call("MOVE", "12", '"Archive"')


@pytest.mark.anyio
@pytest.mark.parametrize("reason", ["folder", "uidplus", "message_id"])
async def test_imap_unsupported_move_does_not_mutate(imap, reason):
    row = message()
    if reason == "folder":
        imap.list.return_value = ("OK", [])
    elif reason == "uidplus":
        imap.capabilities = (b"IMAP4rev1",)
    else:
        row.rfc_message_id = ""
    with pytest.raises(ActionUnsupportedError):
        await backends.backend_for(account()).apply(row, "archive")
    imap.uid.assert_not_called()
    imap.logout.assert_called_once()


@pytest.mark.anyio
async def test_imap_rejects_failed_command_and_checks_host_before_connect(imap, monkeypatch):
    imap.uid.side_effect = None
    imap.uid.return_value = ("NO", [b"invented diagnostic"])
    with pytest.raises(RuntimeError):
        await backends.backend_for(account()).apply(message(), "mark_read")
    transport.check_mail_host.assert_awaited_once_with("imap.example.test")
    imap.logout.assert_called_once()
    transport.open_imap.reset_mock()
    monkeypatch.setattr(transport, "check_mail_host", AsyncMock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        await backends.backend_for(account()).apply(message(), "archive")
    transport.open_imap.assert_not_called()


@pytest.fixture
def http(monkeypatch):
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"id": "new-id"})
    client = httpx.AsyncClient
    monkeypatch.setattr(backends.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value=""))
    return calls


@pytest.mark.anyio
async def test_graph_move_updates_provider_uid(http):
    result = await backends.backend_for(account("microsoft", "oauth2")).apply(message(), "archive")
    assert result == {"provider_uid": "new-id"}
    assert http[-1][0] == "POST" and http[-1][1].endswith("/me/messages/12/move")
    assert http[-1][2] == {"destinationId": "archive"}


@pytest.mark.anyio
async def test_gmail_archive_and_restore_labels(http):
    backend = backends.backend_for(account("google", "oauth2"))
    result = await backend.apply(message(labels_json='["INBOX", "UNREAD"]'), "archive")
    assert json.loads(result["labels_json"]) == ["UNREAD"]
    assert http[-1][2]["removeLabelIds"] == ["INBOX"]
    await backend.apply(message(folder="TRASH", labels_json='["TRASH"]'), "restore")
    assert any(path.endswith("/untrash") for _, path, _ in http)
    assert http[-1][2]["addLabelIds"] == ["INBOX"]


@pytest.mark.anyio
async def test_graph_revert_uses_current_id_and_preserves_it_for_read_only_undo(http):
    backend = backends.backend_for(account("microsoft", "oauth2"))
    previous = {"folder": "INBOX", "is_read": False, "provider_uid": "obsolete", "labels_json": "[]"}
    result = await backend.revert(message(), previous)
    assert result["provider_uid"] == "12"
    assert http[-1][0] == "PATCH" and http[-1][1].endswith("/12")
    assert http[-1][2] == {"isRead": False}
    result = await backend.revert(message(folder="TRASH"), previous)
    assert result["provider_uid"] == "new-id"
    assert http[-2][2] == {"destinationId": "inbox"}
    assert http[-1][1].endswith("/new-id")


@pytest.mark.anyio
async def test_connector_trash_uses_label_or_reports_unsupported(monkeypatch):
    call = AsyncMock(return_value="{}")
    monkeypatch.setattr(connectors, "call_write_tool", call)
    result = await backends.backend_for(account("gmail", connectors.CONNECTOR)).apply(message(labels_json='["INBOX"]'), "trash")
    call.assert_any_await("gmail", "label_message", {"messageId": "12", "labelIds": ["TRASH"]})
    call.assert_any_await("gmail", "unlabel_message", {"messageId": "12", "labelIds": ["INBOX"]})
    assert json.loads(result["labels_json"]) == ["TRASH"]
