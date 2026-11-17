"""Calendar UI fixtures cannot reach a provider, even if adapters become available."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from api.calendar import sync
from api.calendar.seed_ids import SEED_CALENDAR_IDS
from api.mail import dev_seed


@pytest.mark.asyncio
async def test_calendar_seed_never_enqueues_or_dispatches(monkeypatch):
    enqueue = AsyncMock(side_effect=AssertionError("must not enqueue"))
    get = AsyncMock(side_effect=AssertionError("must not dispatch"))
    monkeypatch.setattr(sync.mail_job, "enqueue", enqueue)
    monkeypatch.setattr(sync.calendar_source, "get", get)
    start = datetime(2026, 11, 13, tzinfo=UTC)
    for source_id in SEED_CALENDAR_IDS:
        assert not await sync.enqueue(source_id, start, start + timedelta(days=1))
        await sync.run_sync({"source_id": source_id}, "test-only", 1)
    enqueue.assert_not_called()
    get.assert_not_called()


@pytest.mark.asyncio
async def test_calendar_fixture_shapes(monkeypatch):
    from db.accessors import calendar_seed
    replace = AsyncMock()
    monkeypatch.setattr(calendar_seed, "replace", replace)
    monkeypatch.setattr(dev_seed, "require_local_database", lambda: None)
    await dev_seed.seed_calendars(datetime(2026, 11, 13, 12, tzinfo=UTC))
    sources, events, occurrences, states = replace.call_args.args
    assert {row.id for row in sources} == SEED_CALENDAR_IDS
    assert {row.provider for row in sources} == {"google", "ics"}
    assert sum(row.title == "Planung" for row in occurrences) == 2
    assert len({row.source_id for row in occurrences if row.title == "Planung"}) == 2
    assert any(row.start_date for row in occurrences)
    assert any(len(row.title) > 80 for row in occurrences)
    assert any(not row.is_active for row in sources)
    assert any(row.coverage_start is None for row in states)
    assert len(events) == len(occurrences) == 4
