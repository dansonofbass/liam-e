"""Connection creation is atomic, idempotent and isolated by connector identity."""

import asyncio
import json
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_idempotent_concurrent_connect_and_other_identity(pg_db):
    async def run():
        from db.accessors import calendar_source
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource
        from db.models.calendar_sync_state import CalendarSyncState
        from db.models.mail_job import MailJob

        selections = [{"id": name, "name": "Example", "timezone": "UTC"} for name in ("work@example.org", "garden@example.org")]
        args = {"now": datetime.now(UTC), "interval": 5}
        first, repeat = await asyncio.gather(
            calendar_source.connect_google("google_calendar#first", selections, **args),
            calendar_source.connect_google("google_calendar#first", list(reversed(selections)), **args),
        )
        assert [row.id for row in first] == list(reversed([row.id for row in repeat]))
        paused = await calendar_source.set_active(first[0].id, False)
        again = await calendar_source.connect_google("google_calendar#first", [{**selections[0], "name": "Changed", "timezone": "Europe/Berlin"}], **args)
        assert again[0].id == first[0].id and again[0].name == "Example" and again[0].timezone == "UTC"
        assert again[0].revision == paused.revision and not again[0].is_active
        other = await calendar_source.connect_google("google_calendar#second", selections, **args)
        assert {row.id for row in first}.isdisjoint(row.id for row in other)
        assert {row.id for row in await calendar_source.list_connection("google", "google_calendar#first")} == {row.id for row in first}
        async with get_session_maker()() as session:
            jobs = list((await session.execute(select(MailJob))).scalars())
            assert len(jobs) == 4
            assert {json.loads(job.payload_json)["source_id"] for job in jobs} == {row.id for row in first + other}
            assert all(job.kind == "calendar_sync" for job in jobs)
            states = list((await session.execute(select(CalendarSyncState))).scalars())
            assert len(states) == 4 and all(row.last_error is None for row in states)
        await calendar_source.remove(first[0].id)
        async with get_session_maker()() as session:
            assert len(list((await session.execute(select(CalendarSource))).scalars())) == 3
            assert len(list((await session.execute(select(MailJob))).scalars())) == 3
    asyncio.run(run())
