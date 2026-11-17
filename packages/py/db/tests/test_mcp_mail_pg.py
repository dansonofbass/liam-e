"""Live Postgres contracts for the scoped agent mail index services."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_read_services_use_only_selects_and_scope_every_query(pg_db, monkeypatch):
    async def run():
        from api.mcp import mail
        from api.mcp.access import ReadGrant
        from db.accessors import mail_account, mail_message, mail_sync_state
        from db.engine import get_engine
        from sqlalchemy import event
        from sqlalchemy.orm import Session

        first = await mail_account.create_account(provider="imap", auth_type="imap_password", email_address="a@example.org", display_name="A")
        second = await mail_account.create_account(provider="imap", auth_type="imap_password", email_address="b@example.org", display_name="B")
        now = datetime.now(UTC)
        await mail_sync_state.save_state(account_id=first.id, status="ok", last_sync_at=now)
        one = await mail_message.upsert_message(account_id=first.id, folder="INBOX", provider_uid="1", subject="Example", internal_date=now)
        two = await mail_message.upsert_message(account_id=first.id, folder="INBOX", provider_uid="2", subject="Example", internal_date=now - timedelta(seconds=1), is_read=True)
        foreign = await mail_message.upsert_message(account_id=second.id, folder="INBOX", provider_uid="3", subject="Example", internal_date=now)
        trashed = await mail_message.upsert_message(account_id=first.id, folder="TRASH", provider_uid="4", subject="Example", internal_date=now)

        def forbidden(*args, **kwargs):
            pytest.fail("read service attempted a write")

        statements = []

        def check_statement(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
            assert statement.lstrip().upper().startswith("SELECT"), "non-read SQL"

        engine = get_engine().sync_engine
        event.listen(engine, "before_cursor_execute", check_statement)
        with monkeypatch.context() as patch:
            patch.setattr(Session, "flush", forbidden)
            patch.setattr(Session, "commit", forbidden)
            grant = ReadGrant(frozenset({first.id}))
            assert [a.id for a in (await mail.liam_mail_accounts(grant)).accounts] == [first.id]
            page = await mail.liam_mail_search(grant, query="Example", limit=1)
            assert [m.id for m in page.untrusted_messages] == [one.id]
            page = await mail.liam_mail_search(grant, query="Example", limit=1, cursor=page.next_cursor)
            assert [m.id for m in page.untrusted_messages] == [two.id]
            assert (await mail.liam_mail_read(grant, one.id)).untrusted_message.id == one.id
            with pytest.raises(Exception) as error:
                await mail.liam_mail_read(grant, foreign.id)
            assert error.value.status_code == 404
            with pytest.raises(Exception) as error:
                await mail.liam_mail_read(grant, trashed.id)
            assert error.value.status_code == 404
            summary = await mail.liam_mail_summary(grant)
            assert (summary.total, summary.unread) == (2, 1)
            assert summary.index[0].last_sync_at is not None
            assert (await mail.liam_mail_search(ReadGrant(frozenset()), query="Example")).untrusted_messages == []
        event.remove(engine, "before_cursor_execute", check_statement)
        assert statements

    asyncio.run(run())
