"""Postgres contracts for calendar writing; synthetic data only."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_PG_CONTRACT"), reason="RUN_PG_CONTRACT is not set")


def test_replace_window_sets_capabilities_in_the_same_transaction(pg_db):
    async def run():
        from db.accessors import calendar_source, mail_job
        from db.accessors.calendar_snapshot import LostClaim, replace_window
        from db.engine import get_session_maker
        from db.models.calendar_source import CalendarSource

        source = CalendarSource(provider="google", connection_ref="synthetic", external_id="synthetic", name="Example", timezone="UTC")
        async with get_session_maker()() as session:
            session.add(source)
            await session.commit()
        job = await mail_job.enqueue("calendar", {"source_id": source.id}, dedupe_key="capabilities")
        claim = await mail_job.claim_next(datetime.now(UTC) + timedelta(seconds=1), stale_after=timedelta(minutes=5))
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        args = dict(source_id=source.id, job_id=job.id, attempt=claim.attempts,
                    start=start, end=end, start_date=start.date(), end_date=end.date(),
                    events=[], occurrences=[], expected_revision=source.revision)
        for value in ('["read","write"]', '["read"]'):
            await replace_window(**args, capabilities_json=value)
            assert (await calendar_source.get(source.id)).capabilities_json == value
        with pytest.raises(LostClaim):
            await replace_window(**{**args, "attempt": claim.attempts + 1}, capabilities_json='["read","write"]')
        assert (await calendar_source.get(source.id)).capabilities_json == '["read"]'
    asyncio.run(run())
