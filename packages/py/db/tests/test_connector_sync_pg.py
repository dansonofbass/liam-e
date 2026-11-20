"""Provider observations, stable connector identities and atomic publication."""
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from api.mail import connector_mailbox, connectors, service, sync
from db.accessors import mail_message, mail_sync_state
from db.engine import get_session_maker
from db.models.mail_insight import MailInsight
from db.models.mail_message import MailMessage
from db.models.mail_sync_state import MailSyncState


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
        async with mail_sync_state.connector_transaction(account.id, state, verified=True) as (session, locked):
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


@pytest.mark.parametrize("legacy_copy", [False, True])
def test_connector_provider_restore_and_rearchive_commit_with_new_arrival(pg_db, monkeypatch, legacy_copy):
    async def run():
        account, state, anchor = await connected()
        now = datetime.now(UTC)
        stamps = {"held": now - timedelta(days=1), "new": now}
        inbox = {"held"}
        arrivals = ["held"]

        async def provider(_, tool, args):
            if args.get("threadId") == "anchor":
                return anchor
            if tool == "get_thread":
                uid = args["threadId"]
                return {"id": uid, "messages": [{"id": uid, "date": stamps[uid].isoformat(), "labelIds": ["INBOX", "UNREAD"]}]}
            ids = inbox if "newer_than:" in args["query"] else arrivals
            return {"threads": [{"id": uid, "messages": [{"id": uid, "labelIds": ["INBOX", "UNREAD"]}]} for uid in ids]}

        monkeypatch.setattr(connectors, "call_read_tool_json", provider)
        assert (await sync.sync_account(account.id)).status == "ok"
        original = (await mail_message.known_uids(account.id, "INBOX"))["held"]
        inbox.clear()
        arrivals.clear()
        assert (await sync.sync_account(account.id)).status == "ok"
        assert (await mail_message.get_message(original)).folder == "ARCHIVE"

        inbox.add("held")
        async with get_session_maker().begin() as session:
            locked = await session.get(MailSyncState, state.id)
            locked.connector_deferred_threads = ["held"]
        assert (await sync.sync_account(account.id)).status == "ok"
        assert (await mail_message.known_uids(account.id, "INBOX"))["held"] == original
        assert await mail_message.known_uids(account.id, "ARCHIVE") == {}
        if legacy_copy:
            async with get_session_maker().begin() as session:
                duplicate = MailMessage(account_id=account.id, folder="ARCHIVE", provider_uid="held")
                session.add(duplicate)
                session.add(MailInsight(message_id=duplicate.id, model="synthetic"))

        inbox.remove("held")
        inbox.add("new")
        arrivals.append("new")
        assert (await sync.sync_account(account.id)).status == "ok"
        assert set(await mail_message.known_uids(account.id, "INBOX")) == {"new"}
        assert await mail_message.known_uids(account.id, "ARCHIVE") == {"held": original}
        assert "INBOX" not in json.loads((await mail_message.get_message(original)).labels_json)
        assert (await mail_sync_state.get_state(account.id)).cursor == str(int(now.timestamp()))
        if legacy_copy:
            async with get_session_maker()() as session:
                assert await session.scalar(select(MailInsight.id).where(MailInsight.message_id == duplicate.id)) is None
    asyncio.run(run())
