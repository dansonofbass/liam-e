"""Provider sends preserve reply threading and recipient intent."""

import base64
import json
from email import message_from_bytes
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from db.models.mail_account import MailAccount
from db.models.mail_message import MailMessage

from api.mail import connectors, send, service, transport


def original():
    return MailMessage(account_id="a", provider_uid="provider-id", subject="Nebenkostenabrechnung 2025", sender="Hausverwaltung Kurz <info@hv-kurz.example>", sender_address="info@hv-kurz.example", rfc_message_id="original@example.org", references="<older@example.org>", thread_id="thread", body_text="Hallo\n\nText", internal_date=datetime(2026, 11, 13, 7, 57, tzinfo=timezone.utc), recipients_json=json.dumps(["mira@example.org", "toni@example.org"]), cc_json=json.dumps(["TONI@example.org", "info@hv-kurz.example", "lea@example.org"]))


def test_quote_original_format():
    assert send.quote_original(original()) == "Am 13.11. um 08:57 schrieb Hausverwaltung Kurz <info@hv-kurz.example>:\n> Hallo\n>\n> Text"


def test_reply_all_includes_cc_without_own_address():
    account = MailAccount(email_address="MIRA@example.org")
    assert send.reply_recipients(original(), account, reply_all=True) == (["info@hv-kurz.example"], ["toni@example.org", "lea@example.org"])
    assert send.reply_recipients(original(), account, reply_all=False) == (["info@hv-kurz.example"], [])


@pytest.mark.anyio
async def test_send_reply_sets_threading_headers(monkeypatch):
    server = Mock()
    monkeypatch.setattr(transport, "open_smtp", Mock(return_value=server))
    monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
    monkeypatch.setattr(service, "imap_password", AsyncMock(return_value="password"))
    await send.send_message(MailAccount(provider="imap", email_address="mira@example.org"), to=["info@hv-kurz.example"], cc=["lea@example.org"], subject=original().subject, body="Antwort", reply_to=original(), credentials={"smtp_host": "smtp.example.org"})
    message = server.send_message.call_args.args[0]
    assert message["In-Reply-To"] == "<original@example.org>"
    assert message["References"] == "<older@example.org> <original@example.org>"
    assert message["Subject"] == "Re: Nebenkostenabrechnung 2025"
    assert message["Cc"] == "lea@example.org"


@pytest.mark.anyio
async def test_connector_reply_passes_reply_to_message_id(monkeypatch):
    call = AsyncMock(return_value="sent")
    monkeypatch.setattr(connectors, "call_write_tool", call)
    await send.send_message(MailAccount(provider="gmail", auth_type=connectors.CONNECTOR), to=["info@hv-kurz.example"], cc=["lea@example.org"], subject="Hallo", body="Text", reply_to=original())
    assert call.call_args.args[2] == {"to": ["info@hv-kurz.example"], "cc": ["lea@example.org"], "subject": "Re: Hallo", "body": "Text", "replyToMessageId": "provider-id"}


@pytest.mark.anyio
async def test_gmail_reply_raw_and_thread_id(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "sent-id"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://gmail.example.org")
    monkeypatch.setattr(send.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value="token"))
    await send.send_message(MailAccount(provider="google", email_address="mira@example.org"), to=["info@hv-kurz.example"], cc=["lea@example.org"], subject="Re: Hallo", body="Antwort", reply_to=original(), credentials={})
    payload = json.loads(requests[0].content)
    message = message_from_bytes(base64.urlsafe_b64decode(payload["raw"] + "=" * (-len(payload["raw"]) % 4)))
    assert payload["threadId"] == "thread"
    assert message["In-Reply-To"] == "<original@example.org>"
    assert message["References"] == "<older@example.org> <original@example.org>"
    assert message["Cc"] == "lea@example.org"
    assert message["Subject"] == "Re: Hallo"


@pytest.mark.anyio
async def test_connector_forward_is_new_mail(monkeypatch):
    call = AsyncMock(return_value="sent")
    monkeypatch.setattr(connectors, "call_write_tool", call)
    await send.send_message(MailAccount(provider="gmail", auth_type=connectors.CONNECTOR), to=["toni@example.org"], subject="Hallo", body="Text", forward_of=original())
    assert call.call_args.args[2] == {"to": ["toni@example.org"], "subject": "Wg: Hallo", "body": "Text"}


@pytest.mark.anyio
@pytest.mark.parametrize("mode,operation", [("reply", "createReply"), ("reply_all", "createReplyAll"), ("forward", "createForward")])
async def test_graph_reply_uses_create_reply_then_send(monkeypatch, mode, operation):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "draft-id"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://graph.example.org")
    monkeypatch.setattr(send.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value="token"))
    await send.send_message(MailAccount(provider="microsoft"), to=["toni@example.org"], cc=["lea@example.org"], subject="Hallo", body="Antwort", reply_to=original() if mode != "forward" else None, forward_of=original() if mode == "forward" else None, reply_all=mode == "reply_all", credentials={})
    assert [(r.method, r.url.path) for r in requests] == [("POST", f"/me/messages/provider-id/{operation}"), ("PATCH", "/me/messages/draft-id"), ("POST", "/me/messages/draft-id/send")]
    assert json.loads(requests[1].content)["ccRecipients"] == [{"emailAddress": {"address": "lea@example.org"}}]
