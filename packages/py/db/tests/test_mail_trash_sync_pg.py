"""Trash actions and inbox observations through the ordinary mail routes, with a local provider."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from api.mail import connector_mailbox, connectors, service, sync
from api.routers.api.v1.mail import actions, messages
from db.accessors import mail_action, mail_message, mail_sync_state
from db.engine import get_session_maker
from db.models.mail_message import MailMessage


pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")
MAIL = "/api/v1/mail"


def client():
    app = FastAPI()
    app.include_router(messages.router, prefix=MAIL + "/messages")
    app.include_router(actions.router, prefix=MAIL + "/actions")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def listed(browser, folder):
    response = await browser.get(MAIL + "/messages", params={"folder": folder})
    assert response.status_code == 200
    return {item["id"] for item in response.json()["items"]}


class StudioMailbox:
    """The search replica can lag. Point reads and writes see the actual message labels."""

    def __init__(self):
        self.date = datetime.now(UTC).isoformat()
        self.labels = {"target": {"INBOX"}, "sibling": {"INBOX"}}
        self.replay = False
        self.replayed_target_labels = ["INBOX"]
        self.reject = None
        self.reject_tool = None
        self.writes = []

    async def connect(self, monkeypatch, *, verified=True):
        email = "owner@example.test" if verified else "gmail@connector.mistral"
        self.account = await service.upsert_account(provider="gmail", auth_type=connectors.CONNECTOR, email_address=email)
        progress = connector_mailbox.encode(("named", "anchor", "proof"), "") if verified else ""
        await mail_sync_state.save_state(account_id=self.account.id, connector_verified=verified, connector_cursor=progress)
        async def credentials(*args):
            return {"credentials": [{"name": "named", "authentication_type": "oauth2"}]}
        monkeypatch.setattr(connectors, "_get", credentials)
        monkeypatch.setattr(connectors, "_post", self.dispatch)
        assert (await sync.sync_account(self.account.id)).status == "ok"
        return await mail_message.known_uids(self.account.id, "INBOX")

    async def dispatch(self, path, payload):
        args = payload["arguments"]
        tool = urlsplit(path).path.split("/")[-2]
        if tool in {"label_message", "unlabel_message"}:
            self.writes.append((tool, args["messageId"], tuple(args["labelIds"])))
            if self.reject is not None and self.reject_tool in (None, tool):
                return self.reject
            labels = self.labels[args["messageId"]]
            if tool == "label_message":
                labels.update(args["labelIds"])
            else:
                labels.difference_update(args["labelIds"])
            data = {"id": args["messageId"], "labelIds": sorted(labels)}
        elif args.get("threadId") == "anchor":
            data = {"id": "anchor", "messages": [{"id": "proof", "sender": self.account.email_address, "labelIds": ["SENT"]}]}
        else:
            use_replica = self.replay and args.get("messageFormat") != "MINIMAL"
            rows = [{"id": uid, "labelIds": self.replayed_target_labels if use_replica and uid == "target" else sorted(labels),
                     "date": self.date, "subject": uid, "sender": "sender@example.test"}
                    for uid, labels in self.labels.items()]
            thread = {"id": "mixed", "messages": rows}
            if tool == "get_thread":
                assert args["threadId"] == thread["id"]
                data = thread
            else:
                assert tool == "search_threads"
                data = {"threads": [thread]}
        return {"content": [{"type": "text", "text": json.dumps(data)}]}


@pytest.mark.parametrize("verified", [True, False], ids=["bound", "inbox-only"])
def test_trash_survives_replayed_inbox_and_restores_same_message(pg_db, monkeypatch, verified):
    async def run():
        provider = StudioMailbox()
        ids = await provider.connect(monkeypatch, verified=verified)
        target, sibling = ids["target"], ids["sibling"]
        async with client() as browser:
            result = await browser.post(f"{MAIL}/messages/{target}/actions", json={"kind": "trash"})
            assert result.status_code == 200
            assert provider.labels == {"target": {"TRASH"}, "sibling": {"INBOX"}}
            assert await listed(browser, "INBOX") == {sibling}
            assert await listed(browser, "TRASH") == {target}
            provider.replay = True
            for _ in range(2):
                assert (await sync.sync_account(provider.account.id)).status == "ok"
                assert await listed(browser, "INBOX") == {sibling}
                assert await listed(browser, "TRASH") == {target}
            provider.replay = False
            provider.labels["target"] = {"INBOX"}  # The owner moves it back at the provider.
            assert (await sync.sync_account(provider.account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {target, sibling}
            assert await listed(browser, "TRASH") == set()
            assert len(provider.writes) == 2
    asyncio.run(run())


def test_trash_during_inflight_inbox_snapshot_then_undo(pg_db, monkeypatch):
    async def run():
        provider = StudioMailbox()
        ids = await provider.connect(monkeypatch)
        target, sibling = ids["target"], ids["sibling"]
        # Resume an initial history page. It can contain a UID already in the local index.
        state = await mail_sync_state.get_state(provider.account.id)
        progress = "initial:" + json.dumps([str(int(datetime.fromisoformat(provider.date).timestamp())), "page2"])
        await mail_sync_state.save_state(account_id=provider.account.id, connector_cursor=connector_mailbox.encode(
            connector_mailbox.decode(state.connector_cursor)[0], progress))
        fetched, publish = asyncio.Event(), asyncio.Event()
        fetch = sync._connector_changes
        async def delayed(*args):
            batch = await fetch(*args)
            assert any(row["provider_uid"] == "target" for row in batch[0].upserts)
            fetched.set()
            await publish.wait()
            return batch
        monkeypatch.setattr(sync, "_connector_changes", delayed)
        async with client() as browser:
            pending = asyncio.create_task(sync.sync_account(provider.account.id))
            await asyncio.wait_for(fetched.wait(), 5)
            try:
                result = await browser.post(f"{MAIL}/messages/{target}/actions", json={"kind": "trash"})
                assert result.status_code == 200
                assert await listed(browser, "INBOX") == {sibling}
            finally:
                publish.set()
                await pending
            assert await listed(browser, "INBOX") == {sibling}
            assert await listed(browser, "TRASH") == {target}
            undone = await browser.post(MAIL + "/actions/undo", json={"action_ids": [result.json()["action_id"]]})
            assert undone.json()["restored"] == [result.json()["action_id"]]
            assert provider.labels["target"] == {"INBOX"}
            assert await listed(browser, "INBOX") == {target, sibling}
    asyncio.run(run())


@pytest.mark.parametrize("rejection", [
    {"isError": True, "content": [{"text": "private diagnostic"}]},
    {"content": [{"text": "Provider rejected this label"}]},
    {"content": [{"text": "{}"}]},
], ids=["tool-error", "text-error", "unconfirmed-noop"])
def test_refused_trash_never_hides_mail_or_records_success(pg_db, monkeypatch, rejection):
    async def run():
        provider = StudioMailbox()
        ids = await provider.connect(monkeypatch)
        provider.reject = rejection
        async with client() as browser:
            result = await browser.post(f"{MAIL}/messages/{ids['target']}/actions", json={"kind": "trash"})
            assert result.status_code == 502
            assert result.json()["detail"]["code"] == "provider_failed"
            assert len(provider.writes) == 1  # A failed add of TRASH must not remove INBOX.
            assert await mail_action.latest_open(ids["target"]) is None
            assert await listed(browser, "TRASH") == set()
            assert await listed(browser, "INBOX") == set(ids.values())
    asyncio.run(run())


def test_trash_coalesces_existing_folder_copies_without_losing_links(pg_db, monkeypatch):
    async def run():
        provider = StudioMailbox()
        ids = await provider.connect(monkeypatch)
        async with get_session_maker().begin() as session:
            await session.execute(text("SELECT set_config('liam.verified_connector', :id, true)"), {"id": provider.account.id})
            copies = [MailMessage(account_id=provider.account.id, provider_uid="target", thread_id="mixed",
                                  folder=folder) for folder in ("ARCHIVE", "TRASH")]
            session.add_all(copies)
        async with client() as browser:
            res = await browser.post(f"{MAIL}/messages/{ids['target']}/actions", json={"kind": "trash"})
            assert res.status_code == 200
            assert provider.labels["target"] == {"TRASH"}
            assert await listed(browser, "INBOX") == {ids["sibling"]}
            assert await listed(browser, "ARCHIVE") == set()
            assert await listed(browser, "TRASH") == {ids["target"]}
            for copy in copies:
                assert (await mail_message.get_message(copy.id)).id == ids["target"]
    asyncio.run(run())


@pytest.mark.parametrize("provider_name", ["google", "microsoft", "imap"])
def test_older_native_poll_cannot_publish_after_move(pg_db, monkeypatch, provider_name):
    from unittest.mock import AsyncMock, MagicMock
    from api.mail import sync_gmail, sync_graph, sync_imap, transport
    from api.mail.sync_types import BODY_VERSION, SyncChanges

    async def run():
        account = await service.upsert_account(provider=provider_name, auth_type="imap_password" if provider_name == "imap" else "oauth2",
                                               email_address="native@example.test")
        row = await mail_message.upsert_message(account_id=account.id, folder="INBOX", provider_uid="12",
            rfc_message_id="<duplicate@example.test>", body_version=BODY_VERSION)
        sibling = await mail_message.upsert_message(account_id=account.id, folder="INBOX", provider_uid="13",
            rfc_message_id=row.rfc_message_id, body_version=BODY_VERSION)
        await mail_sync_state.save_state(account_id=account.id, cursor="7:13")
        provider = {"google": sync_gmail, "microsoft": sync_graph, "imap": sync_imap}[provider_name]
        fetched, publish = asyncio.Event(), asyncio.Event()
        async def old_page(*args, **kwargs):
            fetched.set()
            await publish.wait()
            return SyncChanges(upserts=[{"folder": "INBOX", "provider_uid": "12", "body_text": "",
                                         "rfc_message_id": row.rfc_message_id}], cursor="later")
        monkeypatch.setattr(provider, "fetch_changes", old_page)
        monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={"imap_host": "imap.example.test"}))
        monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value="test"))
        monkeypatch.setattr(service, "imap_password", AsyncMock(return_value="test"))
        monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
        imap = MagicMock(capabilities=(b"MOVE",))
        imap.login.return_value = imap.select.return_value = ("OK", [])
        imap.list.return_value = ("OK", [b'(\\Trash) "/" "Deleted"'])
        imap.uid.side_effect = lambda command, *args: ("OK", [b"12"] if command == "SEARCH" else [])
        imap.response.side_effect = lambda name: (name, [b"7 12 91"] if name == "COPYUID" else [b"7"])
        monkeypatch.setattr(transport, "open_imap", lambda *_: imap)
        browser = client()
        real_client = httpx.AsyncClient
        def http_provider(req):
            if req.url.host == "graph.microsoft.com":
                assert req.url.path.endswith("/me/messages/12/move") and json.loads(req.content) == {"destinationId": "deleteditems"}
                return httpx.Response(201, json={"id": "moved"})
            if req.method == "GET":
                return httpx.Response(200, json={"id": "12", "labelIds": ["TRASH"]})
            assert req.url.path.endswith("/messages/12/trash")
            return httpx.Response(200, json={"id": "12", "labelIds": ["TRASH"]})
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(http_provider), **kw))
        async with browser:
            pending = asyncio.create_task(sync.sync_account(account.id))
            await asyncio.wait_for(fetched.wait(), 5)
            try:
                result = await browser.post(f"{MAIL}/messages/{row.id}/actions", json={"kind": "trash"})
                assert result.status_code == 200
                assert await listed(browser, "INBOX") == {sibling.id}
                if provider_name == "imap":
                    imap.uid.assert_any_call("MOVE", "12", '"Deleted"')
            finally:
                publish.set()
                await pending
            assert await listed(browser, "INBOX") == {sibling.id}
            assert await listed(browser, "TRASH") == {row.id}
            assert (await mail_sync_state.get_state(account.id)).cursor == "7:13"
    asyncio.run(run())


def test_graph_delta_replay_after_id_changing_trash_and_undo(pg_db, monkeypatch):
    from unittest.mock import AsyncMock
    from api.mail.sync_types import BODY_VERSION

    async def run():
        account = await service.upsert_account(provider="microsoft", auth_type="oauth2", email_address="outlook@example.test")
        target = await mail_message.upsert_message(account_id=account.id, folder="INBOX", provider_uid="old", body_version=BODY_VERSION)
        delta = "https://graph.microsoft.com/v1.0/delta"
        await mail_sync_state.save_state(account_id=account.id, cursor=delta)
        browser = client()
        real_client = httpx.AsyncClient
        current = "old"
        def respond(req):
            nonlocal current
            path = req.url.path
            if path.endswith("/move"):
                destination = json.loads(req.content)["destinationId"]
                assert path.endswith(f"/messages/{current}/move")
                current = {"deleteditems": "in-trash", "inbox": "back"}[destination]
                return httpx.Response(201, json={"id": current})
            if req.method == "PATCH":  # restore the old read flag
                assert path.endswith("/messages/in-trash")
                return httpx.Response(200, json={})
            if path.endswith("/delta"):
                return httpx.Response(200, json={"@odata.deltaLink": delta, "value": [{"id": "old"}, {"id": "other"}]})
            assert req.method == "GET" and path.endswith("/mailFolders/inbox/messages/old")
            return httpx.Response(404)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
        monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={}))
        monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value="test"))
        async with browser:
            result = await browser.post(f"{MAIL}/messages/{target.id}/actions", json={"kind": "trash"})
            assert result.status_code == 200 and current == "in-trash"
            assert await listed(browser, "INBOX") == set()
            assert (await sync.sync_account(account.id)).status == "ok"
            assert set(await mail_message.known_uids(account.id, "INBOX")) == {"other"}
            undone = await browser.post(MAIL + "/actions/undo", json={"action_ids": [result.json()["action_id"]]})
            assert undone.json()["restored"] == [result.json()["action_id"]]
            assert (await mail_message.known_uids(account.id, "INBOX"))["back"] == target.id and current == "back"
            assert (await sync.sync_account(account.id)).status == "ok"
            assert set(await mail_message.known_uids(account.id, "INBOX")) == {"other", "back"}
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["trash", "undo"])
def test_native_provider_move_overlapping_rebuild_keeps_action_id(pg_db, monkeypatch, kind):
    """The other ordering: the provider moved the mail, then sync commits before the action ack."""
    from unittest.mock import AsyncMock
    from api.mail import sync_graph
    from api.mail.sync_types import BODY_VERSION, SyncChanges

    async def run():
        account = await service.upsert_account(provider="microsoft", auth_type="oauth2", email_address="overlap@example.test")
        target = await mail_message.upsert_message(account_id=account.id, folder="INBOX", provider_uid="first",
                                                  rfc_message_id="<item@example.test>", body_version=BODY_VERSION)
        browser = client()
        real_client = httpx.AsyncClient
        async def dispatch(req):
            if req.method == "PATCH":
                return httpx.Response(200, json={})
            destination = json.loads(req.content)["destinationId"]
            is_undo = destination == "inbox"
            uid = "back" if is_undo else "in-trash"
            if (kind == "undo") == is_undo:
                page = SyncChanges(cursor="next", full_rebuild=True)
                if is_undo:
                    page.upserts.append({"folder": "INBOX", "provider_uid": uid,
                                         "rfc_message_id": target.rfc_message_id, "body_text": ""})
                monkeypatch.setattr(sync_graph, "fetch_changes", AsyncMock(return_value=page))
                assert (await sync.sync_account(account.id)).status == "ok"
            return httpx.Response(201, json={"id": uid})
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(dispatch), **kw))
        monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={}))
        monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value="test"))
        async with browser:
            result = await browser.post(f"{MAIL}/messages/{target.id}/actions", json={"kind": "trash"})
            assert result.status_code == 200 and await listed(browser, "TRASH") == {target.id}
            action_id = result.json()["action_id"]
            undone = await browser.post(MAIL + "/actions/undo", json={"action_ids": [action_id]})
            assert undone.json()["restored"] == [action_id]
            assert (await mail_message.known_uids(account.id, "INBOX")) == {"back": target.id}
            assert await listed(browser, "TRASH") == set()
    asyncio.run(run())


def test_incremental_flags_heal_a_legacy_inbox_copy_of_a_trashed_mail(pg_db, monkeypatch):
    async def run():
        provider = StudioMailbox()
        ids = await provider.connect(monkeypatch)
        async with client() as browser:
            res = await browser.post(f"{MAIL}/messages/{ids['target']}/actions", json={"kind": "trash"})
            assert res.status_code == 200
            # A legacy worker inserted an ordinary, unverified INBOX copy after the trash action.
            old = await mail_message.upsert_message(account_id=provider.account.id, provider_uid="target",
                thread_id="mixed", folder="INBOX", subject="Legacy source", internal_date=datetime.now(UTC))
            provider.replay = True
            assert (await sync.sync_account(provider.account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {ids["sibling"]}
            assert await listed(browser, "TRASH") == {ids["target"]}
            assert await mail_message.get_message(old.id) is None
            legacy = await browser.get(f"{MAIL}/messages/{old.id}")
            assert legacy.json()["local_reference_only"] and legacy.json()["subject"] == "Legacy source"
    asyncio.run(run())


def test_gmail_history_replay_and_real_external_restore(pg_db, monkeypatch):
    from unittest.mock import AsyncMock
    from api.mail.sync_types import BODY_VERSION

    async def run():
        account = await service.upsert_account(provider="google", auth_type="oauth2", email_address="gmail@example.test")
        original = await mail_message.upsert_message(account_id=account.id, folder="INBOX", provider_uid="target",
                                                    labels_json='["INBOX"]', body_version=BODY_VERSION)
        await mail_sync_state.save_state(account_id=account.id, cursor="19")
        browser = client()
        real_client = httpx.AsyncClient
        labels = ["INBOX"]
        replay = ["INBOX"]
        def respond(req):
            if req.url.path.endswith("/trash"):
                labels[:] = ["TRASH"]
                return httpx.Response(200, json={"id": "target", "labelIds": labels})
            if req.url.path.endswith("/history"):
                return httpx.Response(200, json={"historyId": "20", "history": [
                    {"labelsAdded": [{"message": {"id": "target"}}]}]})
            assert req.url.path.endswith("/messages/target")
            return httpx.Response(200, json={"id": "target", "labelIds": replay if req.url.params["format"] == "full" else labels})
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
        monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={}))
        monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value="test"))
        async with browser:
            result = await browser.post(f"{MAIL}/messages/{original.id}/actions", json={"kind": "trash"})
            assert result.status_code == 200
            for observed in (["INBOX", "TRASH"], ["INBOX"]):
                replay[:] = observed
                assert (await sync.sync_account(account.id)).status == "ok"
                assert await listed(browser, "INBOX") == set()
                assert await listed(browser, "TRASH") == {original.id}
            labels[:] = ["INBOX"]
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {original.id} and await listed(browser, "TRASH") == set()
            replay[:] = ["TRASH"]
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {original.id}
            labels[:] = ["TRASH"]
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "TRASH") == {original.id}
    asyncio.run(run())


def test_imap_late_source_uid_replay_and_uidvalidity_reuse(pg_db, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from api.mail import sync_imap, transport
    from api.mail.sync_types import BODY_VERSION, SyncChanges

    async def run():
        account = await service.upsert_account(provider="imap", auth_type="imap_password", email_address="imap@example.test")
        target = await mail_message.upsert_message(account_id=account.id, folder="INBOX", provider_uid="12",
                                                  rfc_message_id="<first@example.test>", body_version=BODY_VERSION)
        existing = await mail_message.upsert_message(account_id=account.id, folder="TRASH", provider_uid="12",
                                                    rfc_message_id="<independent@example.test>", body_version=BODY_VERSION)
        await mail_sync_state.save_state(account_id=account.id, cursor="7:12")
        validity = "7"
        imap = MagicMock(capabilities=(b"MOVE",))
        imap.select.return_value = imap.login.return_value = ("OK", [])
        imap.list.return_value = ("OK", [b'(\\Trash) "/" "Deleted"'])
        imap.response.side_effect = lambda name: (name, [b"7 12 91"] if name == "COPYUID" else [validity.encode()])
        def command(name, *args):
            if name.upper() == "SEARCH":
                return "OK", [b"12"]
            if name.upper() == "FETCH" and validity == "8":
                return "OK", [b"1 (UID 12 FLAGS ())"]
            return "OK", []
        imap.uid.side_effect = command
        monkeypatch.setattr(transport, "open_imap", lambda *_: imap)
        monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
        monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={"imap_host": "imap.example.test"}))
        monkeypatch.setattr(service, "imap_password", AsyncMock(return_value="test"))
        async def page(*args, **kwargs):
            return SyncChanges(cursor=f"{validity}:12", full_rebuild=validity == "8",
                upserts=[{"folder": "INBOX", "provider_uid": "12", "body_text": "", "rfc_message_id":
                         target.rfc_message_id if validity == "7" else "<new@example.test>"}])
        monkeypatch.setattr(sync_imap, "fetch_changes", page)
        async with client() as browser:
            result = await browser.post(f"{MAIL}/messages/{target.id}/actions", json={"kind": "trash"})
            assert result.status_code == 200
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == set()
            assert await listed(browser, "TRASH") == {existing.id, target.id}
            validity = "8"
            assert (await sync.sync_account(account.id)).status == "ok"
            returned = await mail_message.list_page(folder="INBOX")
            assert [row.rfc_message_id for row in returned] == ["<new@example.test>"]
            assert returned[0].id not in {existing.id, target.id}
            assert await listed(browser, "TRASH") == {existing.id, target.id}
    asyncio.run(run())


def test_partial_label_failure_reports_error_then_syncs_actual_trash(pg_db, monkeypatch):
    async def run():
        provider = StudioMailbox()
        ids = await provider.connect(monkeypatch)
        provider.reject = {"isError": True, "content": [{"text": "Refused"}]}
        provider.reject_tool = "unlabel_message"
        async with client() as browser:
            result = await browser.post(f"{MAIL}/messages/{ids['target']}/actions", json={"kind": "trash"})
            assert result.status_code == 502 and await mail_action.latest_open(ids["target"]) is None
            assert provider.labels["target"] == {"INBOX", "TRASH"}
            assert await listed(browser, "INBOX") == set(ids.values())
            assert (await sync.sync_account(provider.account.id)).status == "ok"
            assert await listed(browser, "TRASH") == {ids["target"]}
            assert await listed(browser, "INBOX") == {ids["sibling"]}
    asyncio.run(run())


def test_undo_survives_a_delayed_trash_observation(pg_db, monkeypatch):
    async def run():
        provider = StudioMailbox()
        ids = await provider.connect(monkeypatch)
        async with client() as browser:
            moved = await browser.post(f"{MAIL}/messages/{ids['target']}/actions", json={"kind": "trash"})
            action = moved.json()["action_id"]
            undone = await browser.post(MAIL + "/actions/undo", json={"action_ids": [action]})
            assert undone.json()["restored"] == [action]
            provider.replay = True
            provider.replayed_target_labels = ["TRASH"]
            assert (await sync.sync_account(provider.account.id)).status == "ok"
            assert await listed(browser, "INBOX") == set(ids.values())
            assert await listed(browser, "TRASH") == set()
            provider.labels["target"] = {"TRASH"}  # The owner actually trashes it again.
            assert (await sync.sync_account(provider.account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {ids["sibling"]}
            assert await listed(browser, "TRASH") == {ids["target"]}
    asyncio.run(run())


@pytest.mark.parametrize(("provider", "live_folder"), [
    ("studio", "TRASH"), ("studio", "INBOX"), ("studio", None), ("google", "TRASH"),
    ("microsoft", "TRASH"), ("imap", "TRASH")])
def test_quiet_legacy_duplicate_heals_on_normal_sync(pg_db, monkeypatch, provider, live_folder):
    from unittest.mock import AsyncMock, MagicMock
    from api.mail import transport
    from api.mail.sync_types import BODY_VERSION

    async def run():
        account = await service.upsert_account(provider="gmail" if provider == "studio" else provider,
            auth_type={"studio": connectors.CONNECTOR, "imap": "imap_password"}.get(provider, "oauth2"),
            email_address="owner@example.test")
        old = datetime.now(UTC) - timedelta(days=60)
        progress = {"studio": str(int(old.timestamp()) + 10), "google": "23", "imap": "7:13",
                    "microsoft": "https://graph.microsoft.com/v1.0/delta"}[provider]
        await mail_sync_state.save_state(account_id=account.id, cursor=progress, connector_verified=provider == "studio",
            connector_cursor=connector_mailbox.encode(("named", "anchor", "proof"), progress) if provider == "studio" else "")
        def row(folder, uid):
            return MailMessage(account_id=account.id, folder=folder, provider_uid=uid, thread_id="mixed",
                internal_date=old, body_version=BODY_VERSION, rfc_message_id="<same@example.test>")
        original = row("TRASH", "moved" if provider == "microsoft" else "12")
        ghost, sibling = row("INBOX", "12"), row("INBOX", "13")
        archive = row("ARCHIVE", "12")
        archive.rfc_message_id = "<independent@example.test>"
        pending = {folder: [] for folder in ("INBOX", "TRASH")}
        async with get_session_maker().begin() as session:
            await session.execute(text("SELECT set_config('liam.verified_connector', :id, true)"), {"id": account.id})
            session.add_all([original, ghost, sibling])
            if live_folder is None:
                # A page of inconclusive older pairs must not starve the next pair.
                for folder in pending:
                    pending[folder] = [row(folder, f"00-{i:02d}") for i in range(25)]
                    session.add_all(pending[folder])
            if provider == "imap":
                # An independent archived mail can have the same numeric UID.
                session.add(archive)
        await mail_action.record(message_id=original.id, account_id=account.id, kind="trash",
            previous_json=json.dumps({"provider_uid": "12", "folder": "INBOX", "is_read": False, "labels_json": '["INBOX"]'}))
        browser = client()
        evidence = live_folder
        if provider == "studio":
            async def studio_read(name, tool, args):
                if tool == "search_threads":
                    return {"threads": []}
                assert tool == "get_thread"
                if args["threadId"] == "anchor":
                    return {"id": "anchor", "messages": [{"id": "proof", "sender": account.email_address, "labelIds": ["SENT"]}]}
                assert args["threadId"] == "mixed"
                labels = {"labelIds": [evidence]} if evidence else {}
                return {"id": "mixed", "messages": [{"id": "12", **labels}]}
            monkeypatch.setattr(connectors, "call_read_tool_json", studio_read)
        elif provider == "imap":
            imap = MagicMock()
            imap.login.return_value = imap.select.return_value = ("OK", [])
            imap.response.return_value = ("UIDVALIDITY", [b"7"])
            def command(name, uids, *args):
                if name.lower() == "search":
                    return "OK", [b""]
                assert name.lower() == "fetch"
                return "OK", [b"1 (UID 13 FLAGS ())"] if uids in ("12:13", "13:13") else []
            imap.uid.side_effect = command
            monkeypatch.setattr(transport, "open_imap", lambda *_: imap)
            monkeypatch.setattr(transport, "check_mail_host", AsyncMock())
            monkeypatch.setattr(service, "imap_password", AsyncMock(return_value="test"))
            monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={"imap_host": "imap.example.test"}))
        else:
            real_client = httpx.AsyncClient
            def read(req):
                assert req.method == "GET"
                if req.url.path.endswith("/delta"):
                    return httpx.Response(200, json={"value": [], "@odata.deltaLink": progress})
                if req.url.path.endswith("/history"):
                    return httpx.Response(200, json={"history": [], "historyId": progress})
                assert req.url.path.endswith("/messages/12")
                return httpx.Response(404) if provider == "microsoft" else httpx.Response(200, json={"id": "12", "labelIds": ["TRASH"]})
            monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(read), **kw))
            monkeypatch.setattr(service, "load_credentials", AsyncMock(return_value={}))
            monkeypatch.setattr(service, "valid_access_token", AsyncMock(return_value="test"))
        async with browser:
            async def visible(folder):
                return await listed(browser, folder) - {item.id for item in pending.get(folder, [])}
            assert await visible("INBOX") == {ghost.id, sibling.id}
            if evidence is None:
                for _ in range(2):
                    assert (await sync.sync_account(account.id)).status == "ok"
                    assert await visible("INBOX") == {ghost.id, sibling.id}
                    assert await visible("TRASH") == {original.id}
                evidence = "TRASH"
                assert (await sync.sync_account(account.id)).status == "ok"
                assert ghost.id in await visible("INBOX")  # First repair page, still inconclusive.
            for _ in range(2):
                assert (await sync.sync_account(account.id)).status == "ok"
                assert await visible("INBOX") == ({sibling.id, original.id} if evidence == "INBOX" else {sibling.id})
                assert await visible("TRASH") == (set() if evidence == "INBOX" else {original.id})
                if provider == "imap":
                    assert await listed(browser, "ARCHIVE") == {archive.id}
    asyncio.run(run())
