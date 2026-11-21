"""IMAP identity across reversible flags, rolling upgrades and mailbox resets."""

import asyncio
import json
import os

import pytest

from api.mail import service, sync
from bulk_mailboxes import Mailboxes, YahooConnection
from db.accessors import mail_action, mail_insight, mail_message, mail_sync_state
from db.engine import get_session_maker
from db.models.mail_message import MailMessage
from env.mail import env as mail_env
from test_mail_trash_sync_pg import MAIL, client, listed

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def flag_inbox_delivery(monkeypatch, provider):
    execute = YahooConnection.uid
    writes = []
    def command(connection, cmd, *args):
        if connection.folder == "ARCHIVE" and cmd.upper() == "SEARCH" and "HEADER" in args:
            return "OK", [b"91"] if args[-1] == '"<yahoo-11@example.test>"' else []
        if cmd.upper() in {"STORE", "MOVE", "COPY", "EXPUNGE"}:
            writes.append((connection.folder, cmd.upper(), args[0]))
        status, data = execute(connection, cmd, *args)
        if connection.folder == "INBOX" and cmd.upper() == "FETCH":
            def flagged(header):
                return header.replace(b"FLAGS ()", b"FLAGS (\\Deleted)") if b"UID 11 " in header else header
            data = [(flagged(i[0]), i[1]) if isinstance(i, tuple) else flagged(i) for i in data]
        return status, data
    monkeypatch.setattr(YahooConnection, "uid", command)
    monkeypatch.setattr(YahooConnection, "list", lambda *_: ("OK", [b'(\\Trash) "/" "Trash"', b'(\\Archive) "/" "Archive"']))
    provider.yahoo_folders["ARCHIVE"] = {"91": "91"}  # Independent copy with the same RFC Message-ID.
    provider.labels["Yahoo"]["91"] = {"ARCHIVE"}
    return writes


def test_trash_of_temporarily_deleted_imap_mail_preserves_archive_copy(pg_db, monkeypatch):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        writes = flag_inbox_delivery(monkeypatch, provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        async with client() as browser:
            assert ids["11"] not in await listed(browser, "INBOX")
            result = await browser.post(MAIL + "/messages/actions", json={"message_ids": [ids["11"]], "kind": "trash"})
            row, = result.json()["results"]
            assert row["status"] in {"failed", "unsupported"} and row["action_id"] is None
            assert writes == [] and provider.yahoo_folders["ARCHIVE"] == {"91": "91"}
            assert provider.yahoo_folders["INBOX"]["11"] == "11" and provider.yahoo_folders["TRASH"] == {}
            del provider.yahoo_folders["INBOX"]["11"]
            assert (await sync.sync_account(account.id)).status == "ok" and ids["11"] in await listed(browser, "ARCHIVE")
            retry = await browser.post(MAIL + "/messages/actions", json={"message_ids": [ids["11"]], "kind": "trash"})
            assert retry.json()["results"][0]["status"] == "unsupported" and writes == []
    asyncio.run(run())


def test_previous_imap_worker_can_resume_with_pending_uid_and_open_token(pg_db, monkeypatch):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        async with client() as browser:
            response = await browser.post(f"{MAIL}/messages/{ids['12']}/actions", json={"kind": "mark_read"})
            token = response.json()["action_id"]
            await mail_sync_state.save_state(account_id=account.id, cursor="7:14")
            flag_inbox_delivery(monkeypatch, provider)
            assert (await sync.sync_account(account.id)).status == "ok"
            before = await mail_sync_state.get_state(account.id)
            monkeypatch.setattr(mail_env, "mail_sync_page_size", 1)
            # A previous worker parses everything after the colon as one numeric watermark.
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {ids["12"], ids["13"], ids["14"]}
            undo = await browser.post(MAIL + "/actions/undo", json={"action_ids": [token]})
            assert undo.json()["restored"] == [token] and before.cursor == "7:14"
    asyncio.run(run())


@pytest.mark.parametrize("same_header", [False, True])
def test_imap_undo_into_reused_destination_keeps_both_local_identities(pg_db, monkeypatch, same_header):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        if same_header:
            async with get_session_maker().begin() as session:
                (await session.get(MailMessage, ids["11"])).rfc_message_id = "<yahoo-12@example.test>"
        await mail_insight.store_if_missing(ids["11"], points=["Old delivery"], deadline=None, needs_reply=False,
                                             followups=[], model="test")
        async with client() as browser:
            old_action = (await browser.post(f"{MAIL}/messages/{ids['11']}/actions", json={"kind": "mark_read"})).json()["action_id"]
            trash = (await browser.post(f"{MAIL}/messages/{ids['12']}/actions", json={"kind": "trash"})).json()["action_id"]
            provider.yahoo_folders["INBOX"].clear()
            execute = YahooConnection.uid
            def move(connection, cmd, *args):
                result = execute(connection, cmd, *args)
                if cmd.upper() == "MOVE" and args[-1] == '"INBOX"':
                    provider.yahoo_folders["INBOX"]["11"] = provider.yahoo_folders["INBOX"].pop("212")
                    connection.copied = b"9 112 11"
                return result
            previous = YahooConnection.response
            def generation(connection, key):
                if key == "UIDVALIDITY" and connection.folder == "INBOX":
                    return key, [b"9"]
                return previous(connection, key)
            monkeypatch.setattr(YahooConnection, "uid", move)
            monkeypatch.setattr(YahooConnection, "response", generation)
            undone = await browser.post(MAIL + "/actions/undo", json={"action_ids": [trash]})
            assert undone.status_code == 200 and undone.json()["restored"] == [trash]
            assert (await mail_message.known_uids(account.id, "INBOX"))["11"] == ids["12"]
            assert (await mail_message.get_message(ids["11"])).id == ids["11"]
            assert (await mail_action.get_many([old_action]))[0].message_id == ids["11"]
            assert await mail_insight.get(ids["11"]) is not None
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {ids["12"]}
    asyncio.run(run())


def test_null_generation_trash_origin_cannot_consume_a_later_delivery(pg_db, monkeypatch):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        account = await service.upsert_account(provider="imap", auth_type="imap_password", email_address="Yahoo@example.test")
        await mail_sync_state.save_state(account_id=account.id, cursor="6:14")
        old = await mail_message.upsert_message(account_id=account.id, folder="TRASH", provider_uid="11",
                                                rfc_message_id="<yahoo-11@example.test>")
        await mail_action.record(message_id=old.id, account_id=account.id, kind="trash",
            previous_json=json.dumps({"provider_uid": "11", "folder": "INBOX", "is_read": False, "labels_json": "[]"}))
        await provider.connect(monkeypatch)  # The normal generation-7 rebuild sees a separate delivery.
        ids = await mail_message.known_uids(account.id, "INBOX")
        await mail_insight.store_if_missing(ids["11"], points=["Later delivery"], deadline=None, needs_reply=False,
                                             followups=[], model="test")
        del provider.yahoo_folders["INBOX"]["11"]
        async with client() as browser:
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == set(ids.values()) - {ids["11"]}
            assert await listed(browser, "TRASH") == {old.id}
            assert await listed(browser, "ARCHIVE") == {ids["11"]}
            assert await mail_insight.get(ids["11"]) is not None
    asyncio.run(run())
