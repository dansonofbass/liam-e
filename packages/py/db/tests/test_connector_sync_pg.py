"""Provider observations, stable connector identities and atomic publication."""
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from api.mail import connector_mailbox, connectors, service, sync
from db.accessors import chat_settings, mail_account, mail_message, mail_sync_state
from db.engine import get_session_maker
from db.models.mail_insight import MailInsight
from db.models.mail_message import MailMessage
from db.models.task_series import TaskSeries


pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


async def connected():
    account = await service.upsert_account(provider="gmail", auth_type=connectors.CONNECTOR, email_address="indexed@example.test")
    cursor = connector_mailbox.encode(("named", "anchor", "proof"), "15")
    state = await mail_sync_state.save_state(account_id=account.id, cursor="15", connector_cursor=cursor, connector_verified=True)
    anchor = {"id": "anchor", "messages": [{"id": "proof", "sender": account.email_address, "labelIds": ["SENT"]}]}
    return account, state, anchor


def test_label_free_retry_keeps_confirmed_unread_and_existing_star(pg_db, monkeypatch):
    async def run():
        account, state, anchor = await connected()
        now = datetime.now(UTC)
        async with mail_sync_state.sync_transaction(account.id, state, verified=True) as (session, locked):
            row = await mail_message.upsert_message(session=session, account_id=account.id, folder="INBOX", thread_id="held",
                provider_uid="item", internal_date=now, is_read=True, is_flagged=True, labels_json='["INBOX","STARRED"]')
            locked.connector_deferred_threads = ["held"]
        queries = []

        async def provider(_, tool, args):
            if args.get("threadId") == "anchor":
                return anchor
            if tool == "get_thread":
                return {"id": "held", "messages": [{"id": "item", "date": now.isoformat()}]}
            queries.append(args["query"])
            return {"threads": [{"id": "held"}]}

        monkeypatch.setattr(connectors, "call_read_tool_json", provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        assert "is:unread in:inbox newer_than:14d" in queries and any("before:" in q for q in queries)
        persisted = await mail_message.get_message(row.id)
        assert not persisted.is_read and persisted.is_flagged
        assert set(json.loads(persisted.labels_json)) == {"INBOX", "UNREAD", "STARRED"}
    asyncio.run(run())


@pytest.mark.parametrize("legacy_copy,bare_listing", [(False, False), (False, True), (True, False)])
def test_connector_provider_restore_and_rearchive_commit_with_new_arrival(pg_db, monkeypatch, legacy_copy, bare_listing):
    async def run():
        account, state, anchor = await connected()
        now = datetime.now(UTC)
        stamps = {"held": now - timedelta(days=1), "middle": now - timedelta(hours=1), "new": now}
        inbox = {"held"}
        arrivals = ["held"]

        async def provider(_, tool, args):
            if args.get("threadId") == "anchor":
                return anchor
            if tool == "get_thread":
                uid = args["threadId"]
                return {"id": uid, "messages": [{"id": uid, "date": stamps[uid].isoformat(), "labelIds": ["INBOX", "UNREAD"]}]}
            ids = inbox if "newer_than:" in args["query"] else arrivals
            if bare_listing:
                return {"threads": [{"id": uid} for uid in ids]}
            return {"threads": [{"id": uid, "messages": [{"id": uid, "labelIds": ["INBOX", "UNREAD"]}]} for uid in ids]}

        monkeypatch.setattr(connectors, "call_read_tool_json", provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        original = (await mail_message.known_uids(account.id, "INBOX"))["held"]
        async with get_session_maker().begin() as session:
            task = TaskSeries(scope="app", creation_key="source-link", creation_hash="synthetic", title="Follow up",
                              source_account_id=account.id, source_message_id=original)
            session.add(task)
        inbox.remove("held")
        inbox.add("middle")
        arrivals[:] = ["middle"]
        assert (await sync.sync_account(account.id)).status == "ok"
        assert (await mail_message.get_message(original)).folder == "ARCHIVE"
        state = await mail_sync_state.get_state(account.id)
        assert state.cursor == str(int(stamps["middle"].timestamp())) and not state.connector_deferred_threads

        inbox.add("held")
        arrivals.clear()
        if legacy_copy:
            # A prior version restored the provider message as a second, verified inbox row.
            async with mail_sync_state.sync_transaction(account.id, state, verified=True) as (session, _):
                restored = MailMessage(account_id=account.id, folder="INBOX", provider_uid="held", thread_id="held",
                                       internal_date=stamps["held"], labels_json='["INBOX","UNREAD"]')
                session.add(restored)
                session.add(MailInsight(message_id=original, model="synthetic"))
        assert (await sync.sync_account(account.id)).status == "ok"
        kept = restored.id if legacy_copy else original
        assert (await mail_message.known_uids(account.id, "INBOX"))["held"] == kept

        inbox.remove("held")
        inbox.add("new")
        arrivals.append("new")
        assert (await sync.sync_account(account.id)).status == "ok"
        assert set(await mail_message.known_uids(account.id, "INBOX")) == {"middle", "new"}
        assert await mail_message.known_uids(account.id, "ARCHIVE") == {"held": kept}
        assert "INBOX" not in json.loads((await mail_message.get_message(original)).labels_json)
        assert (await mail_sync_state.get_state(account.id)).cursor == str(int(now.timestamp()))
        async with get_session_maker()() as session:
            saved = await session.get(TaskSeries, task.id)
            assert (await mail_message.get_message(saved.source_message_id, session)).id == kept
        assert await mail_message.get_scoped_message(original, ["another-account"], folder="ARCHIVE") is None
        assert (await mail_message.get_scoped_message(original, [account.id], folder="ARCHIVE")).id == kept
        if legacy_copy:
            assert await mail_message.resolve_aliases([original, kept]) == {original: kept}
            async with get_session_maker()() as session:
                assert await session.scalar(select(MailInsight.id).where(MailInsight.message_id == original)) is None
            assert await chat_settings.mail_preview(original, 1, None) is None
            grant = await chat_settings.update(1, [account.id])
            assert (await chat_settings.mail_preview(original, grant.version, None))[0].id == kept
            await chat_settings.invalidate_connector(account.id)
            assert await mail_message.get_message(original) is None
    asyncio.run(run())


def test_recent_restores_reread_quarantined_mail_in_bounded_batches(pg_db, monkeypatch):
    async def run():
        account, _, anchor = await connected()
        now = datetime.now(UTC)
        archived = [MailMessage(id=f"local-{i}", account_id=account.id, provider_uid=f"item-{i}", thread_id=f"item-{i}",
                                folder="ARCHIVE", internal_date=now, body_text="Unchecked", unverified_connector=True)
                    for i in range(7)]
        async with get_session_maker().begin() as session:
            session.add_all(archived)
        content_reads = []

        async def provider(_, tool, args):
            if args.get("threadId") == "anchor":
                return anchor
            if tool == "get_thread":
                assert connectors.mailbox_credential.get() == "named"
                uid = args["threadId"]
                content_reads.append(uid)
                if uid == "item-0" and content_reads.count(uid) == 1:
                    return None
                return {"id": uid, "messages": [{"id": uid, "date": now.isoformat(), "plaintextBody": "Verified", "labelIds": ["INBOX"]}]}
            listed = archived if "newer_than:" in args["query"] else []
            return {"threads": [{"id": row.thread_id, "messages": [{"id": row.provider_uid, "labelIds": ["INBOX"]}]} for row in listed]}

        monkeypatch.setattr(connectors, "call_read_tool_json", provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        assert len(content_reads) == 5
        assert set(await mail_message.known_uids(account.id, "INBOX", verified_only=True)) == {f"item-{i}" for i in range(1, 5)}
        assert (await mail_message.get_message("local-0")).unverified_connector
        assert (await sync.sync_account(account.id)).status == "ok"
        assert len(content_reads) == 8 and not (await mail_sync_state.get_state(account.id)).connector_deferred_threads
        for old in archived:
            row = await mail_message.get_message(old.id)
            assert (row.folder, row.body_text, row.unverified_connector) == ("INBOX", "Verified", False)
    asyncio.run(run())


def test_upgrade_preserves_unverified_archived_task_source_as_read_only(pg_db, monkeypatch):
    from fastapi import HTTPException
    from api.routers.api.v1.mail import messages

    async def run():
        account = await service.upsert_account(provider="gmail", auth_type=connectors.CONNECTOR, email_address="owner@example.test")
        await mail_sync_state.save_state(account_id=account.id, cursor="15")
        old = MailMessage(account_id=account.id, provider_uid="same", folder="ARCHIVE",
                          body_text="Original task source", unverified_connector=True)
        inbox = MailMessage(account_id=account.id, provider_uid="same", folder="INBOX", unverified_connector=True)
        task = TaskSeries(scope="app", creation_key="original-link", creation_hash="fixture", title="Follow up",
                          source_account_id=account.id, source_message_id=old.id)
        async with get_session_maker().begin() as session:
            session.add_all([old, inbox, task])
        anchor = {"id": "sent", "messages": [{"id": "sent-item", "sender": account.email_address, "labelIds": ["SENT"]}]}
        now = datetime.now(UTC)
        async def provider(_, tool, args):
            if args.get("query") == "in:sent from:me":
                return {"threads": [anchor]}
            if args.get("threadId") == "sent":
                return anchor
            if tool == "search_threads":
                return {"threads": [{"id": "thread"}]}
            return {"id": "thread", "messages": [{"id": "same", "date": now.isoformat(),
                    "plaintextBody": "Freshly verified content", "labelIds": ["INBOX"]}]}
        monkeypatch.setattr(connector_mailbox, "_credential", AsyncMock(return_value="named"))
        monkeypatch.setattr(connectors, "call_read_tool_json", provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        live = await messages.get_message(inbox.id)
        assert live.body_text == "Freshly verified content" and not live.local_reference_only
        async with get_session_maker()() as session:
            source_id = (await session.get(TaskSeries, task.id)).source_message_id
        saved = await messages.get_message(source_id)
        assert saved.id == old.id and saved.body_text == "Original task source" and saved.local_reference_only
        assert not saved.can_show_original and not saved.can_unsubscribe
        grant = await chat_settings.update(1, [account.id])
        assert await chat_settings.mail_preview(old.id, grant.version, None) is None
        assert await mail_message.get_message(old.id) is None
        assert await mail_message.resolve_aliases([old.id]) == {}
        assert await mail_account.delete_account(account.id)
        with pytest.raises(HTTPException) as error:
            await messages.get_message(source_id)
        assert error.value.status_code == 404
    asyncio.run(run())


@pytest.mark.parametrize("still_in_inbox", [True, False])
def test_restore_checks_recent_per_message_labels_after_reading_mixed_thread(pg_db, monkeypatch, still_in_inbox):
    async def run():
        account, state, anchor = await connected()
        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)
        async with mail_sync_state.sync_transaction(account.id, state, verified=True) as (session, locked):
            watermark = str(int(now.timestamp()))
            locked.cursor = watermark
            locked.connector_cursor = connector_mailbox.encode(("named", "anchor", "proof"), watermark)
            local = {uid: MailMessage(account_id=account.id, provider_uid=uid, thread_id="mixed", folder="ARCHIVE",
                                      internal_date=yesterday) for uid in ("target", "sibling")}
            session.add_all(local.values())
        reads = []
        async def provider(_, tool, args):
            if args.get("threadId") == "anchor":
                return anchor
            if tool == "get_thread":
                assert connectors.mailbox_credential.get() == "named"
                reads.append("content")
                return {"id": "mixed", "messages": [{"id": uid, "date": yesterday.isoformat(),
                        "plaintextBody": "Bound content"} for uid in local]}
            query = args["query"]
            if query == "in:inbox newer_than:14d":
                reads.append("recent")
                labels = ["INBOX", "UNREAD", "STARRED"] if still_in_inbox or "content" not in reads else []
                return {"threads": [{"id": "mixed", "messages": [
                    {"id": "target", "labelIds": labels}, {"id": "sibling", "labelIds": []}]}]}
            if "before:" in query:
                return {"threads": [{"id": "mixed"}]}
            return {"threads": []}
        monkeypatch.setattr(connectors, "call_read_tool_json", provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        assert reads == ["recent", "content", "recent"]
        assert (await mail_message.get_message(local["sibling"].id)).folder == "ARCHIVE"
        target = await mail_message.get_message(local["target"].id)
        assert target.folder == ("INBOX" if still_in_inbox else "ARCHIVE")
        if still_in_inbox:
            assert target.body_text == "Bound content" and not target.is_read and target.is_flagged
        assert not (await mail_sync_state.get_state(account.id)).connector_deferred_threads
    asyncio.run(run())
