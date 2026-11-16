"""Live Postgres contracts for calendar index constraints and overlap."""

import asyncio
import os
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_occurrence_identity_and_overlap(pg_db):
    async def run():
        from db.accessors.calendar_occurrence import overlapping
        from db.engine import get_session_maker
        from db.models.calendar_occurrence import CalendarOccurrence

        async with get_session_maker()() as session:
            session.add(CalendarOccurrence(source_id="a", event_id="e", external_id="one", start_date=date(2026, 1, 1), end_date=date(2026, 1, 4)))
            session.add(CalendarOccurrence(source_id="b", event_id="e", external_id="one", start_date=date(2026, 1, 1), end_date=date(2026, 1, 4)))
            await session.commit()
        rows = await overlapping(["a"], start=datetime(2026, 1, 2, tzinfo=UTC), end=datetime(2026, 1, 3, tzinfo=UTC), start_date=date(2026, 1, 2), end_date=date(2026, 1, 3))
        assert len(rows) == 1 and rows[0].source_id == "a"
        async with get_session_maker()() as session:
            session.add(CalendarOccurrence(source_id="a", event_id="e", external_id="one", start_date=date(2026, 1, 2), end_date=date(2026, 1, 3)))
            with pytest.raises(IntegrityError):
                await session.commit()

    asyncio.run(run())
