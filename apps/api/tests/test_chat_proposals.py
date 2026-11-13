"""Proposal confirmation is explicit, atomic and safe to expose."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from db.models.chat_message import ChatMessage
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.mail import connectors, proposals, service, transport
from api.mail.chat_schemas import to_message_out
from api.routers.api.v1.chat.proposals import router

pytestmark = pytest.mark.anyio


@pytest.fixture
async def store(fake_store, monkeypatch):
    rows = {}

    async def add(**kwargs):
        row = ChatMessage(**kwargs)
        rows[row.id] = row
        return row

    async def get(id):
        return rows.get(id)

    async def claim(id):
        row = rows.get(id)
        if row and row.proposal_status == "pending":
            row.proposal_status = "running"
            return row
        return None

    async def cancel(id):
        row = rows.get(id)
        if row and row.proposal_status == "pending":
            row.proposal_status = "cancelled"
            return row
        return None

    async def cancel_open(conversation_id):
        for row in rows.values():
            if row.conversation_id == conversation_id and row.proposal_status == "pending":
                row.proposal_status = "cancelled"

    async def update(id, **kwargs):
        for key, value in kwargs.items():
            setattr(rows[id], key, value)
        return rows[id]

    for name, fn in [("add_message", add), ("get_message", get), ("claim_proposal", claim), ("cancel_proposal", cancel), ("cancel_open_proposals", cancel_open), ("set_proposal", update)]:
        monkeypatch.setattr(proposals.message_access, name, fn)
    account = await fake_store.create_account(provider="gmail", auth_type=connectors.CONNECTOR, email_address="mira@example.org")
    return account


def draft(account):
    return proposals.Proposal(kind="send", reason="Antwort", items=[], draft=proposals.SendDraft(account_id=account.id, mode="new", to=["toni@example.org"], cc=[], subject="Hallo", body="Text", quote="", reply_to_message_id=None), irreversible=True, result=None)


def mail_proposal():
    return proposals.Proposal(kind="archive", reason="Aufräumen", items=[proposals.ProposalItem(id=str(i), kind="mail", title="Mail", subtitle="", count=None, unread=None, last_read_at=None, method=None) for i in range(3)], draft=None, irreversible=False, result=None)


async def test_new_proposal_cancels_previous_open_one(store):
    first = await proposals.create_proposal("chat", draft(store))
    second = await proposals.create_proposal("chat", draft(store))
    assert first.proposal_status == "cancelled"
    assert second.proposal_status == "pending"


async def test_confirm_executes_only_selected_items(store, monkeypatch):
    action = AsyncMock(return_value=SimpleNamespace(id="undo"))
    monkeypatch.setattr(proposals.actions, "apply_action", action)
    monkeypatch.setattr(proposals.mail_access, "get_message", AsyncMock(return_value=SimpleNamespace(folder="INBOX")))
    row = await proposals.create_proposal("chat", mail_proposal())
    result = await proposals.confirm(row.id, selected_ids=["1"])
    action.assert_awaited_once_with("1", "archive")
    assert proposals.proposal_view(result).result.done == 1
    assert [i.selected for i in proposals.proposal_view(result).items] == [False, True, False]


async def test_confirm_twice_runs_once(store, monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(proposals.send, "send_message", send)
    row = await proposals.create_proposal("chat", draft(store))
    results = await asyncio.gather(*(proposals.confirm(row.id, selected_ids=[]) for _ in range(2)), return_exceptions=True)
    assert sum(isinstance(r, proposals.ProposalStateError) for r in results) == 1
    assert sum(isinstance(r, ChatMessage) for r in results) == 1
    send.assert_awaited_once()


async def test_confirm_skips_items_gone_since_proposal(store, monkeypatch):
    monkeypatch.setattr(proposals.actions, "apply_action", AsyncMock(return_value=SimpleNamespace(id="undo")))
    monkeypatch.setattr(proposals.mail_access, "get_message", AsyncMock(side_effect=[SimpleNamespace(folder="INBOX"), SimpleNamespace(folder="ARCHIVE"), SimpleNamespace(folder="INBOX")]))
    row = await proposals.create_proposal("chat", mail_proposal())
    await proposals.confirm(row.id, selected_ids=["0", "1", "2"])
    assert row.proposal_status == "partial"
    result = proposals.proposal_view(row).result
    assert result.done == 2
    assert [p.model_dump() for p in result.failed] == [{"id": "1", "code": "item_gone"}]


async def test_cancel_after_confirm_is_409(store, monkeypatch):
    monkeypatch.setattr(proposals.send, "send_message", AsyncMock())
    row = await proposals.create_proposal("chat", draft(store))
    await proposals.confirm(row.id, selected_ids=[])
    app = FastAPI()
    app.include_router(router, prefix="/proposals")
    response = TestClient(app).post(f"/proposals/{row.id}/cancel")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "proposal_not_pending"


async def test_confirm_sends_connector_without_credentials(store, monkeypatch):
    monkeypatch.setattr(service, "load_credentials", AsyncMock(side_effect=AssertionError("credentials loaded")))
    call = AsyncMock(return_value="sent")
    monkeypatch.setattr(connectors, "call_write_tool", call)
    row = await proposals.create_proposal("chat", draft(store))
    await proposals.confirm(row.id, selected_ids=[])
    assert row.proposal_status == "done"
    call.assert_awaited_once_with("gmail", "send_email", {"to": ["toni@example.org"], "subject": "Hallo", "body": "Text"})


@pytest.mark.parametrize("error,code", [(transport.MailHostNotAllowedError("private"), "host_not_allowed"), (RuntimeError("secret-ish provider text"), "send_failed")])
async def test_send_errors_are_safe(store, monkeypatch, error, code):
    monkeypatch.setattr(proposals.send, "send_message", AsyncMock(side_effect=error))
    row = await proposals.create_proposal("chat", draft(store))
    await proposals.confirm(row.id, selected_ids=[])
    assert row.proposal_status == "failed"
    assert proposals.proposal_view(row).result.failed[0].code == code
    assert "secret-ish" not in row.proposal_json + to_message_out(row).model_dump_json()


async def test_legacy_draft_rows_read_as_send_proposals():
    for old, new in [("sent", "done"), ("pending", "cancelled"), ("failed", "failed"), ("cancelled", "cancelled")]:
        row = ChatMessage(conversation_id="chat", role="draft", draft_json=json.dumps({"account_id": "a", "to": [], "subject": "Hallo", "body": "Text", "status": old}))
        output = to_message_out(row)
        assert output.proposal.kind == "send"
        assert output.proposal.draft.mode == "new"
        assert output.proposal_status == new


@pytest.mark.parametrize("selection,code", [([], "selection_empty"), (["unknown"], "selection_invalid")])
async def test_invalid_selection_does_not_claim(store, selection, code):
    row = await proposals.create_proposal("chat", mail_proposal())
    with pytest.raises(proposals.ProposalSelectionError) as error:
        await proposals.confirm(row.id, selected_ids=selection)
    assert error.value.code == code
    assert row.proposal_status == "pending"


async def test_cancel_only_pending_and_unknown_is_not_found(store):
    row = await proposals.create_proposal("chat", draft(store))
    assert (await proposals.cancel(row.id)).proposal_status == "cancelled"
    with pytest.raises(proposals.ProposalStateError):
        await proposals.cancel(row.id)
    with pytest.raises(proposals.ProposalNotFoundError):
        await proposals.confirm("missing", selected_ids=[])


async def test_unsubscribe_results_and_manual_steps(store, monkeypatch):
    proposal = mail_proposal()
    proposal.kind = "unsubscribe"
    for item in proposal.items:
        item.kind = "sender"
    monkeypatch.setattr(proposals.newsletters, "sender_by_id", AsyncMock(return_value=SimpleNamespace(account_id=store.id)))
    monkeypatch.setattr(proposals.newsletters, "unsubscribe", AsyncMock(side_effect=[
        SimpleNamespace(status="done", archived_action_ids=["undo-1"]),
        SimpleNamespace(status="manual", link="https://newsletter.example.org/leave", archived_action_ids=["undo-2"]),
        SimpleNamespace(status="failed", error_code="unsubscribe_failed"),
    ]))
    row = await proposals.create_proposal("chat", proposal)
    await proposals.confirm(row.id, selected_ids=["0", "1", "2"])
    result = proposals.proposal_view(row).result
    assert row.proposal_status == "partial"
    assert result.done == 1
    assert result.manual[0].id == "1"
    assert result.failed[0].code == "unsubscribe_failed"
    assert result.undo_action_ids == ["undo-1", "undo-2"]


async def test_unsubscribe_without_link_is_manual_step(store, monkeypatch):
    proposal = proposals.Proposal(kind="unsubscribe", reason="Newsletter", items=[proposals.ProposalItem(id="sender|news@example.org", kind="sender", title="News", subtitle="", count=2, unread=0, last_read_at=None, method="none")], draft=None, irreversible=True, result=None)
    monkeypatch.setattr(proposals.newsletters, "sender_by_id", AsyncMock(return_value=SimpleNamespace(account_id=store.id, method="none")))
    monkeypatch.setattr(proposals.newsletters, "unsubscribe", AsyncMock(return_value=SimpleNamespace(status="manual", link=None, archived_action_ids=["a1", "a2"])))
    row = await proposals.create_proposal("chat", proposal)
    await proposals.confirm(row.id, selected_ids=["sender|news@example.org"])
    result = proposals.proposal_view(row).result
    assert row.proposal_status == "done"
    assert [step.model_dump() for step in result.manual] == [{"id": "sender|news@example.org", "link": None}]
    assert result.failed == []
    assert result.undo_action_ids == ["a1", "a2"]


async def test_unexpected_failure_never_leaves_running(store, monkeypatch):
    async def explode(*args):
        raise RuntimeError("private")
    monkeypatch.setattr(proposals, "_send", explode)
    row = await proposals.create_proposal("chat", draft(store))
    with pytest.raises(RuntimeError):
        await proposals.confirm(row.id, selected_ids=[])
    assert row.proposal_status == "failed"
    assert proposals.proposal_view(row).result.done == 0
    assert "private" not in row.proposal_json


async def test_send_replaces_body_and_preserves_quote(store, monkeypatch):
    proposal = draft(store)
    proposal.draft.quote = "> Original"
    proposal.draft.mode = "reply_all"
    proposal.draft.reply_to_message_id = "mail"
    original = SimpleNamespace(id="mail")
    monkeypatch.setattr(proposals.mail_access, "get_message", AsyncMock(return_value=original))
    send = AsyncMock()
    monkeypatch.setattr(proposals.send, "send_message", send)
    row = await proposals.create_proposal("chat", proposal)
    await proposals.confirm(row.id, selected_ids=[], body="Neue Antwort")
    assert send.call_args.kwargs["body"] == "Neue Antwort\n\n> Original"
    assert send.call_args.kwargs["reply_to"] is original
    assert send.call_args.kwargs["reply_all"] is True


async def test_draft_routes_are_gone():
    from api.main import create_app
    app = create_app()
    operations = {op.get("operationId") for path in app.openapi()["paths"].values() for op in path.values()}
    assert "chat_draft_confirm" not in operations
    assert "chat_draft_cancel" not in operations
    assert "chat_proposal_confirm" in operations
