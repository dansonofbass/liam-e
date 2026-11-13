"""Single-message actions and undo contracts."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from db.models.mail_account import MailAccount
from db.models.mail_message import MailMessage

from api.mail import actions, action_backends
from api.routers.api.v1.mail import messages


@pytest.fixture
def setup(fake_store, monkeypatch):
    account = MailAccount(id="a", provider="google", auth_type="oauth2", email_address="ada@example.test")
    message = MailMessage(id="m", account_id="a", provider_uid="uid", labels_json='["INBOX", "UNREAD"]')
    fake_store.accounts[account.id] = account
    fake_store.messages[message.id] = message
    backend = AsyncMock()
    backend.apply.return_value = {}
    backend.revert.return_value = {}
    monkeypatch.setattr(action_backends, "backend_for", lambda _: backend)
    monkeypatch.setattr(messages.insight_access, "get_for_messages", AsyncMock(return_value={}))
    return fake_store, backend


@pytest.mark.anyio
async def test_archive_updates_index_records_action_and_calls_provider(setup):
    store, backend = setup
    async def apply(message, kind):
        assert store.messages["m"].folder == "ARCHIVE"
        assert message.folder == "INBOX"
        assert kind == "archive"
        return {}
    backend.apply.side_effect = apply
    action = await actions.apply_action("m", "archive")
    assert store.messages["m"].folder == "ARCHIVE"
    assert store.actions[action.id] == action
    assert json.loads(action.previous_json)["folder"] == "INBOX"
    backend.apply.assert_awaited_once()


def test_provider_failure_restores_index_and_returns_502(client, setup, caplog):
    store, backend = setup
    backend.apply.side_effect = RuntimeError("private provider diagnostic")
    response = client.post("/api/v1/mail/messages/m/actions", json={"kind": "archive"})
    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "provider_failed", "message": "Das hat beim Anbieter nicht geklappt. Die Mail ist unverändert."}
    assert "private" not in response.text
    assert "private" not in caplog.text
    assert store.messages["m"].folder == "INBOX"
    assert store.messages["m"].labels_json == '["INBOX", "UNREAD"]'
    assert not store.actions


@pytest.mark.anyio
async def test_undo_restores_previous_state_once(setup):
    store, backend = setup
    action = await actions.apply_action("m", "archive")
    result = await actions.undo_actions([action.id], now=datetime.now(UTC))
    assert result.restored == [action.id]
    assert store.messages["m"].folder == "INBOX"
    result = await actions.undo_actions([action.id], now=datetime.now(UTC))
    assert result.skipped == [action.id]
    backend.revert.assert_awaited_once()


@pytest.mark.anyio
async def test_undo_after_24_hours_is_expired(setup):
    _, backend = setup
    action = await actions.apply_action("m", "archive")
    result = await actions.undo_actions([action.id], now=action.created_at + timedelta(hours=24, seconds=1))
    assert result.expired == [action.id]
    backend.revert.assert_not_awaited()


@pytest.mark.anyio
async def test_undo_processes_newest_first_and_skips_superseded(setup):
    store, backend = setup
    first = await actions.apply_action("m", "archive")
    second = await actions.apply_action("m", "restore")
    result = await actions.undo_actions([first.id], now=datetime.now(UTC))
    assert result.skipped == [first.id]
    backend.revert.assert_not_awaited()
    result = await actions.undo_actions([first.id, second.id], now=datetime.now(UTC))
    assert result.restored == [second.id, first.id]
    assert store.messages["m"].folder == "INBOX"


@pytest.mark.anyio
async def test_failed_undo_releases_claim_and_keeps_index(setup):
    store, backend = setup
    action = await actions.apply_action("m", "archive")
    backend.revert.side_effect = RuntimeError("private diagnostic")
    result = await actions.undo_actions([action.id], now=datetime.now(UTC))
    assert result.failed == [action.id]
    assert store.actions[action.id].undone_at is None
    assert store.messages["m"].folder == "ARCHIVE"
    backend.revert.side_effect = None
    assert (await actions.undo_actions([action.id], now=datetime.now(UTC))).restored == [action.id]


@pytest.mark.parametrize("folder,kind", [("ARCHIVE", "archive"), ("TRASH", "trash"), ("INBOX", "restore")])
def test_unsupported_source_is_untouched(client, setup, folder, kind):
    store, backend = setup
    store.messages["m"].folder = folder
    response = client.post("/api/v1/mail/messages/m/actions", json={"kind": kind})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "action_unsupported"
    assert store.messages["m"].folder == folder
    backend.apply.assert_not_awaited()
    assert not store.actions


def test_action_and_undo_routes(client, setup):
    store, _ = setup
    response = client.post("/api/v1/mail/messages/m/actions", json={"kind": "mark_read"})
    assert response.status_code == 200
    assert response.json()["message"]["is_read"] is True
    action_id = response.json()["action_id"]
    response = client.post("/api/v1/mail/actions/undo", json={"action_ids": [action_id, "missing"]})
    assert response.json() == {"restored": [action_id], "expired": [], "skipped": ["missing"], "failed": []}
    assert store.messages["m"].is_read is False
    for ids in ([], ["x"] * 201):
        assert client.post("/api/v1/mail/actions/undo", json={"action_ids": ids}).status_code == 422
    response = client.post("/api/v1/mail/messages/missing/actions", json={"kind": "archive"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "message_not_found"


@pytest.mark.anyio
async def test_undo_claims_before_provider_and_allows_exactly_24_hours(setup):
    store, backend = setup
    action = await actions.apply_action("m", "archive")
    entered, finish = asyncio.Event(), asyncio.Event()
    async def revert(message, previous):
        assert store.actions[action.id].undone_at is not None
        entered.set()
        await finish.wait()
        return {}
    backend.revert.side_effect = revert
    now = action.created_at + timedelta(hours=24)
    pending = asyncio.create_task(actions.undo_actions([action.id], now=now))
    await entered.wait()
    assert (await actions.undo_actions([action.id], now=now)).skipped == [action.id]
    finish.set()
    assert (await pending).restored == [action.id]
    backend.revert.assert_awaited_once()


@pytest.mark.anyio
async def test_undo_orders_equal_timestamps_by_descending_id(setup):
    store, _ = setup
    first = await actions.apply_action("m", "archive")
    second = await actions.apply_action("m", "restore")
    first.created_at = second.created_at
    del store.actions[first.id], store.actions[second.id]
    first.id, second.id = "a", "z"
    store.actions.update(a=first, z=second)
    result = await actions.undo_actions(["a", "z"], now=datetime.now(UTC))
    assert result.restored == ["z", "a"]


def test_backend_unsupported_restores_index(client, setup):
    store, backend = setup
    backend.apply.side_effect = actions.ActionUnsupportedError()
    response = client.post("/api/v1/mail/messages/m/actions", json={"kind": "archive"})
    assert response.status_code == 409
    assert store.messages["m"].folder == "INBOX"
    assert not store.actions


@pytest.mark.anyio
async def test_undo_missing_message_and_duplicate_ids(setup):
    store, backend = setup
    action = await actions.apply_action("m", "archive")
    del store.messages["m"]
    result = await actions.undo_actions([action.id, action.id], now=datetime.now(UTC))
    assert result.skipped == [action.id]
    backend.revert.assert_not_awaited()
