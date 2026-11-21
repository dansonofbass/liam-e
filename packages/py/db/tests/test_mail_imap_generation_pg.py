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
@pytest.mark.parametrize("flag_on_first_poll", [False, True], ids=["visible", "flagged-first-poll"])
def test_imap_undo_into_reused_destination_keeps_both_local_identities(pg_db, monkeypatch, same_header, flag_on_first_poll):
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
        await mail_insight.store_if_missing(ids["12"], points=["Restored delivery"], deadline=None, needs_reply=False,
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
            if flag_on_first_poll:
                with monkeypatch.context() as flagged:
                    flag_inbox_delivery(flagged, provider)
                    assert (await sync.sync_account(account.id)).status == "ok"
                    assert await mail_message.known_uids(account.id, "IMAP_DELETED") == {"9:11": ids["12"]}
                    assert await listed(browser, "INBOX") == set()
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == {ids["12"]}
            assert await mail_message.known_uids(account.id, "IMAP_DELETED") == {}
            assert await listed(browser, "ARCHIVE") == {ids["11"]}
            assert (await mail_action.get_many([trash]))[0].message_id == ids["12"]
            assert json.loads((await mail_insight.get(ids["12"])).points_json) == ["Restored delivery"]
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


@pytest.mark.parametrize("occupied", [True, False])
def test_restore_ack_after_newer_generation_poll_leaves_its_inbox_intact(pg_db, monkeypatch, occupied):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        generation = b"7"
        response = YahooConnection.response
        def selected(connection, name):
            if name == "UIDVALIDITY" and connection.folder == "INBOX":
                return name, [generation]
            return response(connection, name)
        monkeypatch.setattr(YahooConnection, "response", selected)
        async with client() as browser:
            token = (await browser.post(f"{MAIL}/messages/{ids['12']}/actions", json={"kind": "trash"})).json()["action_id"]
            commit = mail_message.commit_trash_move
            newer_uid = "212" if occupied else "241"
            fresh_id = ""
            async def publish_newer_first(message, updates, **kwargs):
                nonlocal generation, fresh_id
                assert updates["imap_uidvalidity"] == "7" and updates["provider_uid"] == "212"
                generation = b"8"
                provider.yahoo_folders["INBOX"] = {newer_uid: "different"}
                provider.labels["Yahoo"]["different"] = {"INBOX"}
                assert (await sync.sync_account(account.id)).status == "ok"
                fresh_id = (await mail_message.known_uids(account.id, "INBOX"))[newer_uid]
                await commit(message, updates, **kwargs)
            monkeypatch.setattr(mail_message, "commit_trash_move", publish_newer_first)
            undo = await browser.post(MAIL + "/actions/undo", json={"action_ids": [token]})
            assert undo.status_code == 200 and undo.json()["restored"] == [token]
            for _ in range(2):
                listing = (await browser.get(MAIL + "/messages")).json()["items"]
                assert [(r["id"], r["subject"]) for r in listing] == [(fresh_id, "Yahoo different")]
                assert (await sync.sync_account(account.id)).status == "ok"
            assert (await mail_message.get_message(ids["12"])).id == ids["12"]
            assert (await browser.post(MAIL + "/actions/undo", json={"action_ids": [token]})).json()["skipped"] == [token]
    asyncio.run(run())


def test_direct_imap_expunge_cannot_dispatch_to_an_unselected_archive_copy(pg_db, monkeypatch):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        del provider.yahoo_folders["INBOX"]["11"]
        writes = flag_inbox_delivery(monkeypatch, provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        async with client() as browser:
            assert ids["11"] in await listed(browser, "ARCHIVE")
            result = await browser.post(MAIL + "/messages/actions", json={"message_ids": [ids["11"]], "kind": "trash"})
            row, = result.json()["results"]
            assert row["status"] == "unsupported" and row["action_id"] is None
            assert writes == [] and provider.yahoo_folders["ARCHIVE"] == {"91": "91"}
            assert await listed(browser, "TRASH") == set()
    asyncio.run(run())


def override_inbox_flags(monkeypatch, uid, flags):
    fetch = YahooConnection.uid
    def command(connection, cmd, *args):
        status, data = fetch(connection, cmd, *args)
        if connection.folder == "INBOX" and cmd.upper() == "FETCH":
            def flagged(header):
                return header.replace(b"FLAGS ()", b"FLAGS (" + flags() + b")") if f"UID {uid} ".encode() in header else header
            data = [(flagged(entry[0]), entry[1]) if isinstance(entry, tuple) else flagged(entry) for entry in data]
        return status, data
    monkeypatch.setattr(YahooConnection, "uid", command)


def test_flagged_destination_poll_before_undo_keeps_the_restored_public_id(pg_db, monkeypatch):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        selected = ids["12"]
        await mail_insight.store_if_missing(selected, points=["Selected"], deadline=None, needs_reply=False, followups=[], model="test")
        async with client() as browser:
            token = (await browser.post(f"{MAIL}/messages/{selected}/actions", json={"kind": "trash"})).json()["action_id"]
            flags = b"\\Deleted \\Seen \\Flagged"
            override_inbox_flags(monkeypatch, "212", lambda: flags)
            commit = mail_message.commit_trash_move
            async def poll_first(message, updates, **kwargs):
                assert (await sync.sync_account(account.id)).status == "ok"
                observed = await mail_message.known_uids(account.id, "IMAP_DELETED")
                assert set(observed) == {"7:212"} and observed["7:212"] != selected
                await commit(message, updates, **kwargs)
            monkeypatch.setattr(mail_message, "commit_trash_move", poll_first)
            undo = await browser.post(MAIL + "/actions/undo", json={"action_ids": [token]})
            assert undo.status_code == 200 and undo.json()["restored"] == [token]
            for _ in range(2):
                assert await listed(browser, "INBOX") == set(ids.values()) - {selected}
                assert await mail_message.known_uids(account.id, "IMAP_DELETED") == {"7:212": selected}
                assert (await sync.sync_account(account.id)).status == "ok"
            flags = b"\\Seen \\Flagged"
            assert (await sync.sync_account(account.id)).status == "ok"
            assert await listed(browser, "INBOX") == set(ids.values())
            assert await mail_message.known_uids(account.id, "IMAP_DELETED") == {}
            restored = await mail_message.get_message(selected)
            assert (restored.provider_uid, restored.is_read, restored.is_flagged) == ("212", True, True)
            assert (await mail_action.get_many([token]))[0].message_id == selected
            assert json.loads((await mail_insight.get(selected)).points_json) == ["Selected"]
    asyncio.run(run())


@pytest.mark.parametrize("flag_before_expunge", [False, True], ids=["direct-expunge", "flag-then-expunge"])
def test_expunge_polled_before_restore_ack_survives_the_next_delivery(pg_db, monkeypatch, flag_before_expunge):
    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        selected = ids["12"]
        controls = set(ids.values()) - {selected}
        await mail_insight.store_if_missing(selected, points=["Selected"], deadline=None, needs_reply=False, followups=[], model="test")
        async with client() as browser:
            token = (await browser.post(f"{MAIL}/messages/{selected}/actions", json={"kind": "trash"})).json()["action_id"]
            commit = mail_message.commit_trash_move
            async def expunge_before_commit(message, updates, **kwargs):
                assert (updates["imap_uidvalidity"], updates["provider_uid"]) == ("7", "212")
                if flag_before_expunge:
                    override_inbox_flags(monkeypatch, "212", lambda: b"\\Deleted")
                assert (await sync.sync_account(account.id)).status == "ok"
                folder, uid = ("IMAP_DELETED", "7:212") if flag_before_expunge else ("INBOX", "212")
                polled_id = (await mail_message.known_uids(account.id, folder))[uid]
                assert polled_id != selected
                del provider.yahoo_folders["INBOX"]["212"]
                assert (await sync.sync_account(account.id)).status == "ok"
                assert await listed(browser, "ARCHIVE") == {polled_id}
                await commit(message, updates, **kwargs)
            monkeypatch.setattr(mail_message, "commit_trash_move", expunge_before_commit)
            undo = await browser.post(MAIL + "/actions/undo", json={"action_ids": [token]})
            assert undo.status_code == 200 and undo.json()["restored"] == [token]
            first_inbox = await listed(browser, "INBOX")
            provider.yahoo_folders["INBOX"]["213"] = "later"
            provider.labels["Yahoo"]["later"] = {"INBOX"}
            poll = await sync.sync_account(account.id)
            current = await mail_message.known_uids(account.id, "INBOX")
            assert (selected in first_inbox, poll.status, "213" in current) == (False, "ok", True)
            assert first_inbox == controls and await listed(browser, "INBOX") == controls | {current["213"]}
            assert await listed(browser, "ARCHIVE") == {selected} and await listed(browser, "TRASH") == set()
            assert (await mail_sync_state.get_state(account.id)).cursor == "7:213"
            assert (await mail_action.get_many([token]))[0].message_id == selected
            assert json.loads((await mail_insight.get(selected)).points_json) == ["Selected"]
            assert (await browser.post(MAIL + "/actions/undo", json={"action_ids": [token]})).json()["skipped"] == [token]
    asyncio.run(run())


@pytest.mark.parametrize("flag_before_expunge", [True, False])
def test_unlocated_imap_original_cannot_show_separate_archive_bytes(pg_db, monkeypatch, flag_before_expunge):
    import env.db
    from previous_imap_poll import run_previous

    async def run():
        provider = Mailboxes(["Yahoo"], False, "move")
        await provider.connect(monkeypatch)
        account = provider.accounts["Yahoo"]
        ids = await mail_message.known_uids(account.id, "INBOX")
        url = f"{MAIL}/messages/{ids['11']}"
        async with client() as browser:
            source = await browser.get(url + "/original")
            assert source.status_code == 200 and "Synthetic message 11." in source.json()["source"]
        flag_inbox_delivery(monkeypatch, provider)
        if flag_before_expunge:
            assert (await sync.sync_account(account.id)).status == "ok"
        del provider.yahoo_folders["INBOX"]["11"]
        assert (await sync.sync_account(account.id)).status == "ok"
        reads = []
        fetch = YahooConnection.uid
        def wire(connection, command, *args):
            if command.upper() == "FETCH" and connection.folder == "ARCHIVE":
                reads.append(args[0])
                return "OK", [(b"1 (UID 91 RFC822.SIZE 70)", b"Subject: Other archive copy\r\n\r\nOther delivery source bytes")]
            return fetch(connection, command, *args)
        monkeypatch.setattr(YahooConnection, "uid", wire)
        async with client() as browser:
            detail = await browser.get(url)
            source = await browser.get(url + "/original")
            assert (source.status_code, detail.json()["can_show_original"], reads) == (409, False, [])
            assert source.json()["detail"]["code"] == "original_unavailable"
            assert (await browser.get(f"{MAIL}/messages/{ids['14']}/original")).status_code == 200
        run_previous(env.db.env.async_database_url, rolling_id=ids["11"])
        # The base backend only knows the physical INBOX, ARCHIVE, TRASH and SPAM folders.
        assert (await mail_message.get_message(ids["11"])).folder not in {"INBOX", "ARCHIVE", "TRASH", "SPAM"}
    asyncio.run(run())
