"""Google snapshots use synthetic fixture pages, never provider access."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState

from api.calendar import google, sync, feed_jobs

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures/google_calendar"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def source(monkeypatch):
    source = CalendarSource(provider="google", connection_ref="google_calendar#" + hashlib.sha256(
        b"google_calendar:work@example.org").hexdigest()[:16], external_id="work@example.org",
        name="Werkstatt", timezone="Europe/Berlin")

    async def get(identifier):
        return source

    async def state(identifier):
        return CalendarSyncState(source_id=identifier, failure_count=1)

    from db.accessors import calendar_source, calendar_sync_state
    monkeypatch.setattr(calendar_source, "get", get)
    monkeypatch.setattr(calendar_sync_state, "get", state)
    return source


async def test_adapter_assembles_pages_and_dispatch_fences_full_window(source, monkeypatch):
    calls = []

    async def call(tool, arguments):
        calls.append((tool, arguments))
        if "calendarId" not in arguments:
            return {"summary": "work@example.org", "events": []}
        return fixture("events_2" if arguments.get("pageToken") else "events_1")

    adapter = google.GoogleConnectorAdapter(call=call, clock=lambda: START)
    result = await adapter.snapshot(source.id, START, END)
    assert result.source_revision == source.revision
    assert len(result.occurrences) == 4
    assert len(result.events) == 3
    assert calls[0][1] == {"startTime": START.isoformat(), "endTime": (START + timedelta(seconds=1)).isoformat(), "pageSize": 1}
    assert calls[1][1] == {"calendarId": source.external_id, "startTime": START.isoformat(), "endTime": END.isoformat(), "pageSize": 250}
    assert calls[2][1] == {**calls[1][1], "pageToken": "synthetic-events-page-2"}
    activated = []

    async def replace(**kwargs):
        activated.append(kwargs)

    from api.calendar import ics
    monkeypatch.setattr(ics, "default_window", lambda: (START, END))
    monkeypatch.setattr(sync, "replace_window", replace)
    monkeypatch.setitem(sync._adapters, "google", adapter)
    await sync.run_sync({"source_id": source.id}, "job", 1)
    assert activated[0]["replace_all"] is True
    assert activated[0]["reset_schedule"] is True
    assert activated[0]["expected_revision"] == source.revision
    assert activated[0]["start"] == START


@pytest.mark.parametrize("failure,expected", [
    ("identity", "reconnect_required"), ("malformed", "provider_unavailable"),
    ("cap", "provider_unavailable"), ("reconnect_required", "reconnect_required"),
    ("calendar_unavailable", "calendar_unavailable"), ("provider_unavailable", "provider_unavailable"),
])
async def test_failed_snapshot_records_only_public_code_and_never_activates(source, monkeypatch, failure, expected):
    from db.accessors import calendar_feed_sync
    from api.calendar import ics
    errors = []
    count = 0

    async def call(tool, arguments):
        nonlocal count
        if "calendarId" not in arguments:
            return {"summary": "other@example.org" if failure == "identity" else "work@example.org", "events": []}
        count += 1
        if failure == "malformed":
            return fixture("malformed")
        if failure == "cap":
            return {"events": [], "nextPageToken": str(count)}
        raise google.GoogleError(failure)

    async def record(identifier, **kwargs):
        errors.append(kwargs)

    async def forbidden(**kwargs):
        pytest.fail("failure must preserve the previous snapshot")

    monkeypatch.setattr(calendar_feed_sync, "failure", record)
    monkeypatch.setattr(ics, "default_window", lambda: (START, END))
    monkeypatch.setattr(sync, "replace_window", forbidden)
    monkeypatch.setitem(sync._adapters, "google", google.GoogleConnectorAdapter(call=call, clock=lambda: START, jitter=lambda a, b: 30))
    with pytest.raises(google.GoogleError, match=f"^{expected}$"):
        await sync.run_sync({"source_id": source.id}, "job", 1)
    assert errors[0]["code"] == expected
    assert errors[0]["revision"] == source.revision
    assert errors[0]["delay_seconds"] == (60 if expected == "provider_unavailable" else None)
    if failure == "identity":
        assert count == 0
    if failure == "cap":
        assert count == 40


@pytest.mark.parametrize("status,expected", [(401, "reconnect_required"), (403, "reconnect_required"),
    (404, "calendar_unavailable"), (429, "provider_unavailable"), (500, "provider_unavailable")])
async def test_http_errors_are_redacted(monkeypatch, status, expected):
    from api.mail import connectors

    async def call(*args):
        response = httpx.Response(status, request=httpx.Request("POST", "https://provider.example/test"))
        raise httpx.HTTPStatusError("test-only-private-text", request=response.request, response=response)

    monkeypatch.setattr(connectors, "_call_tool", call)
    with pytest.raises(google.GoogleError, match=f"^{expected}$"):
        await google.live_call("list_events", {})


async def test_transport_error_redacted(monkeypatch):
    from api.mail import connectors

    async def call(*args):
        raise httpx.ReadTimeout("test-only-private-text")

    monkeypatch.setattr(connectors, "_call_tool", call)
    with pytest.raises(google.GoogleError, match="^provider_unavailable$"):
        await google.live_call("list_events", {})


async def test_google_scheduling_uses_five_minute_setting(source, monkeypatch):
    calls = []

    async def enqueue(identifier, **kwargs):
        calls.append((identifier, kwargs))
        return True

    monkeypatch.setattr(feed_jobs.calendar_feed_sync, "enqueue", enqueue)
    assert await feed_jobs.enqueue(source.id, manual=True, now=START)
    assert calls == [(source.id, {"now": START, "interval": 5, "manual": True})]

    async def active():
        return [source]

    async def purge(now):
        pass

    monkeypatch.setattr(feed_jobs.calendar_source, "list_active", active)
    monkeypatch.setattr(feed_jobs.feeds, "purge", purge)
    await feed_jobs.enqueue_due(START)
    assert calls[-1][1]["manual"] is False
