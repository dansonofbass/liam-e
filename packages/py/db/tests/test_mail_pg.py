"""Live Postgres contracts for the mail index and job queue."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_account_lookup_ignores_case_and_selects_first_deterministically(pg_db):
    async def run():
        from db.accessors import mail_account as a

        first = await a.create_account(provider="imap", auth_type="imap_password", email_address="Max@example.org")
        assert (await a.get_account_by_email("max@example.org")).id == first.id
        assert (await a.get_account(first.id)).email_address == "Max@example.org"
        second = await a.create_account(provider="imap", auth_type="imap_password", email_address="max@example.org")
        second.created_at = first.created_at
        await a.touch_account(second)
        assert (await a.get_account_by_email("MAX@EXAMPLE.ORG")).id == min(first.id, second.id)
        assert await a.get_account_by_email("missing@example.org") is None

    asyncio.run(run())


def test_list_page_pages_with_cursor_without_gaps(pg_db):
    async def run():
        from db.accessors import mail_message as m
        now = datetime.now(UTC)
        rows = [await m.upsert_message(account_id="a", folder="INBOX", provider_uid=str(i), internal_date=now - timedelta(days=i // 2)) for i in range(5)]
        pages = []
        before = None
        for _ in range(3):
            page = await m.list_page(before=before, limit=2)
            pages.extend(page)
            before = (page[-1].internal_date, page[-1].id)
        assert [x.id for x in pages] == [x.id for x in sorted(rows, key=lambda x: (x.internal_date, x.id), reverse=True)]
    asyncio.run(run())


def test_list_page_pages_through_null_dates(pg_db):
    async def run():
        from db.accessors import mail_message as m
        now = datetime.now(UTC)
        rows = [await m.upsert_message(account_id="a", folder="INBOX", provider_uid=str(i), internal_date=now - timedelta(days=i) if i < 2 else None) for i in range(5)]
        pages = []
        before = None
        while page := await m.list_page(before=before, limit=2):
            pages.extend(page)
            before = (page[-1].internal_date, page[-1].id)
        expected = sorted(rows[:2], key=lambda x: (x.internal_date, x.id), reverse=True) + sorted(rows[2:], key=lambda x: x.id, reverse=True)
        assert [x.id for x in pages] == [x.id for x in expected]
    asyncio.run(run())


def test_list_page_filters(pg_db):
    async def run():
        from db.accessors import mail_message as m, mail_insight as ins
        rows = [await m.upsert_message(account_id="b" if i == 4 else "a", folder="INBOX", provider_uid=str(i), is_read=i == 4, has_attachments=i == 3, is_flagged=i == 0) for i in range(5)]
        for i in (1, 2):
            await ins.upsert(rows[i].id, points=[], deadline=date.today() if i == 1 else None, needs_reply=i == 2, followups=[], model="m")
        assert {x.id for x in await m.list_page(important_only=True)} == {x.id for x in rows[:3]}
        assert {x.id for x in await m.list_page(unread_only=True)} == {x.id for x in rows[:4]}
        assert [x.id for x in await m.list_page(with_attachments=True)] == [rows[3].id]
        assert [x.id for x in await m.list_page(account_ids=["b"])] == [rows[4].id]
    asyncio.run(run())


def test_fulltext_matches_german_stems(pg_db):
    async def run():
        from db.accessors import mail_message as m
        row = await m.upsert_message(account_id="a", folder="INBOX", provider_uid="1", body_text="Die Rechnungen kommen morgen")
        assert [x.id for x in await m.list_page(query="Rechnung")] == [row.id]
    asyncio.run(run())


def test_enqueue_dedupes_open_jobs(pg_db):
    async def run():
        from db.accessors import mail_job as j
        job = await j.enqueue("sync", {}, dedupe_key="a")
        assert await j.enqueue("sync", {}, dedupe_key="a") is None
        await j.finish(job.id)
        assert await j.enqueue("sync", {}, dedupe_key="a") is not None
    asyncio.run(run())


def test_claim_next_skips_locked_rows(pg_db):
    async def run():
        from db.accessors import mail_job as j
        await j.enqueue("sync", {}, dedupe_key="a")
        now = datetime.now(UTC)
        result = await asyncio.gather(*(j.claim_next(now, stale_after=timedelta(minutes=5)) for _ in range(2)))
        assert sum(x is not None for x in result) == 1
    asyncio.run(run())


def test_claim_next_reclaims_stale_running_job(pg_db):
    async def run():
        from db.accessors import mail_job as j
        await j.enqueue("sync", {}, dedupe_key="a")
        now = datetime.now(UTC)
        first = await j.claim_next(now, stale_after=timedelta(minutes=5))
        second = await j.claim_next(now + timedelta(minutes=6), stale_after=timedelta(minutes=5))
        assert second.id == first.id and second.attempts == 2
    asyncio.run(run())


def test_mark_undone_is_single_use(pg_db):
    async def run():
        from db.accessors import mail_action as a
        action = await a.record(message_id="m", account_id="a", kind="read", previous_json="{}")
        assert await a.mark_undone(action.id, datetime.now(UTC)) is True
        assert await a.mark_undone(action.id, datetime.now(UTC)) is False
    asyncio.run(run())


def test_newsletter_senders_takes_headers_from_newest_mail(pg_db):
    async def run():
        from db.accessors import mail_message as m
        from db.engine import get_session_maker
        from sqlalchemy import event

        await m.upsert_message(account_id="a", folder="INBOX", provider_uid="old", sender_address="news@example.com", sender="Old", list_unsubscribe="old")
        await m.upsert_message(account_id="a", folder="INBOX", provider_uid="new", sender_address="news@example.com", sender="New", internal_date=datetime.now(UTC), list_unsubscribe="new", list_unsubscribe_post="post", labels_json='["new"]')
        statements = []
        engine = get_session_maker().kw["bind"].sync_engine
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            rows = await m.newsletter_senders()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(rows) == 1
        assert (rows[0].sender_display, rows[0].list_unsubscribe, rows[0].list_unsubscribe_post, rows[0].labels_json) == ("New", "new", "post", '["new"]')
        assert len(statements) == 1
        assert "body_text" not in statements[0].lower()
        assert "count(" in statements[0].lower()
    asyncio.run(run())


def test_newsletter_senders_aggregates_counts(pg_db):
    async def run():
        from db.accessors import mail_message as m
        now = datetime.now(UTC)
        for i in range(3):
            await m.upsert_message(account_id="a", folder="INBOX", provider_uid=str(i), sender_address="news@example.com", sender="News", internal_date=now - timedelta(days=i), is_read=i != 0, list_unsubscribe="latest" if i == 0 else "old")
        rows = await m.newsletter_senders()
        assert len(rows) == 1
        assert (rows[0].total, rows[0].unread, rows[0].last_read_at, rows[0].list_unsubscribe) == (3, 1, now - timedelta(days=1), "latest")
    asyncio.run(run())
