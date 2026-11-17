from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from api.calendar import scope, sync
from api.calendar.adapters import Event, Occurrence, Snapshot, normalize
from db.models.calendar_source import CalendarSource


class SyntheticGoogle:
    async def snapshot(self, source_id, start, end):
        return Snapshot([Event("event")], [Occurrence("instance", "event", start_at=start, end_at=end, timezone="UTC")], True)


class SyntheticICS:
    async def snapshot(self, source_id, start, end):
        return Snapshot([Event("master", recurrence={"rrule": "FREQ=DAILY"})],
                        [Occurrence("original-date", "master", start_date=date(2026, 3, 28), end_date=date(2026, 3, 30))], True)


@pytest.mark.anyio
async def test_snapshot_checks_event_ids_once():
    from types import SimpleNamespace
    from db.accessors.calendar_snapshot import replace_window

    class EventRow:
        source_id = "source"
        recurrence_json = "{}"
        reads = 0
        def __init__(self, identifier):
            self.external_id = identifier
            self.identifier = identifier
        @property
        def id(self):
            type(self).reads += 1
            return self.identifier

    events = [EventRow(str(i)) for i in range(10)]
    rows = [SimpleNamespace(source_id="source", external_id=str(i), event_id="0") for i in range(20)]
    rows[-1].event_id = "unknown"
    with pytest.raises(ValueError, match="unknown event"):
        await replace_window(source_id="source", job_id="job", attempt=1,
                             start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC),
                             start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), events=events, occurrences=rows)
    assert EventRow.reads == len(events)


def test_dst_and_interval_validation():
    zone = ZoneInfo("Europe/Berlin")
    item = Occurrence("one", "event", start_at=datetime(2026, 3, 29, 1, 30, tzinfo=zone),
                      end_at=datetime(2026, 3, 29, 3, 30, tzinfo=zone), timezone="Europe/Berlin")
    normalized = normalize(item)
    assert normalized.start_at == datetime(2026, 3, 29, 0, 30, tzinfo=UTC)
    assert normalized.end_at == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        normalize(Occurrence("one", "event", start_at=datetime(2026, 3, 29, 2, 30, tzinfo=zone),
                             end_at=datetime(2026, 3, 29, 3, 30, tzinfo=zone), timezone="Europe/Berlin"))
    with pytest.raises(ValueError):
        normalize(Occurrence("one", "event", start_date=date(2026, 1, 1), end_date=date(2026, 1, 1)))


@pytest.mark.anyio
@pytest.mark.parametrize("adapter", [SyntheticGoogle(), SyntheticICS()])
async def test_synthetic_adapters_use_same_snapshot_path(monkeypatch, adapter):
    source = CalendarSource(provider="synthetic", connection_ref="example", external_id="calendar", name="Example", timezone="UTC")
    async def get(source_id):
        return source
    calls = []
    async def replace(**kwargs):
        calls.append(kwargs)
    monkeypatch.setattr(sync.calendar_source, "get", get)
    monkeypatch.setattr(sync, "replace_window", replace)
    monkeypatch.setitem(sync._adapters, "synthetic", adapter)
    await sync.run_sync({"source_id": source.id, "start": "2026-03-28T00:00:00+00:00", "end": "2026-03-31T00:00:00+00:00"}, "job", 1)
    assert len(calls) == 1 and len(calls[0]["occurrences"]) == 1


@pytest.mark.anyio
async def test_incomplete_snapshot_never_activates(monkeypatch):
    source = CalendarSource(provider="partial", connection_ref="example", external_id="calendar", name="Example", timezone="UTC")
    class Partial:
        async def snapshot(self, source_id, start, end):
            return Snapshot([], [], False)
    async def get(source_id):
        return source
    async def forbidden(**kwargs):
        pytest.fail("incomplete snapshot activated")
    monkeypatch.setattr(sync.calendar_source, "get", get)
    monkeypatch.setattr(sync, "replace_window", forbidden)
    monkeypatch.setitem(sync._adapters, "partial", Partial())
    with pytest.raises(ValueError):
        await sync.run_sync({"source_id": source.id, "start": "2026-01-01T00:00:00+00:00", "end": "2026-01-02T00:00:00+00:00"}, "job", 1)


@pytest.mark.anyio
async def test_enqueue_deduplicates_by_source(fake_store):
    start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
    assert await sync.enqueue("source", start, end)
    assert not await sync.enqueue("source", start, end)
    assert await sync.enqueue("other", start, end)


@pytest.mark.anyio
async def test_scope_fails_closed_for_disabled_or_deleted_source(monkeypatch):
    source = CalendarSource(provider="synthetic", connection_ref="example", external_id="calendar", name="Example", timezone="UTC", capabilities_json='["write"]')
    async def get(source_id):
        return source
    monkeypatch.setattr(scope.calendar_source, "get", get)
    assert await scope.permits(source.id, "write")
    source.is_active = False
    assert not await scope.permits(source.id, "write")
    source = None
    assert not await scope.permits("missing", "write")
