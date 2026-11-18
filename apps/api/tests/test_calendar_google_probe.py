"""Synthetic-only probe checks; no credential, provider, or database access."""

import importlib.util
import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools/calendar_google_probe.py"
spec = importlib.util.spec_from_file_location("calendar_google_probe", TOOL)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)


def fixture(name):
    return json.loads((probe.FIXTURES / f"{name}.json").read_text())


def test_mapping_all_day_dst_point_series_and_moved_identity():
    snapshot = probe.map_pages([fixture("events_1"), fixture("events_2")], START, END)
    assert snapshot.complete is True
    assert len(snapshot.events) == 3
    assert len(snapshot.occurrences) == 4
    all_day, summer, winter, point = snapshot.occurrences
    assert (all_day.start_date, all_day.end_date) == (date(2026, 10, 12), date(2026, 10, 14))
    assert summer.event_external_id == winter.event_external_id == "synthetic-weekly"
    assert summer.start_at == datetime(2026, 10, 18, 7, tzinfo=UTC)
    assert winter.start_at == datetime(2026, 10, 25, 8, tzinfo=UTC)
    assert winter.start_at - summer.start_at == timedelta(days=7, hours=1)
    assert summer.timezone == winter.timezone == point.timezone == "Europe/Berlin"
    assert point.start_at == point.end_at == datetime(2026, 10, 20, 10, tzinfo=UTC)
    event = next(e for e in snapshot.events if e.external_id == summer.event_external_id)
    assert event.recurrence == {"schema": "google-1", "recurring": True}
    moved = probe.map_pages([fixture("events_moved")], START, END).occurrences[0]
    assert moved.external_id == summer.external_id
    assert moved.event_external_id == summer.event_external_id
    assert moved.start_at == datetime(2026, 10, 19, 9, tzinfo=UTC)


def test_all_day_bad_end_title_and_timezone_fallback():
    page = fixture("events_1")
    page["events"] = [page["events"][0]]
    row = page["events"][0]
    row["end"]["date"] = row["start"]["date"]
    row["summary"] = None
    result = probe.map_pages([page], START, END)
    assert result.occurrences[0].end_date == date(2026, 10, 13)
    assert result.events[0].title == ""
    page = fixture("events_2")
    page["events"] = [page["events"][1]]
    page["timeZone"] = None
    assert probe.map_pages([page], START, END, "America/New_York").occurrences[0].timezone == "America/New_York"
    assert probe.map_pages([page], START, END, "invalid-zone").occurrences[0].timezone == "UTC"


def test_drop_outside_window_and_keep_point_at_start():
    page = fixture("events_2")
    page["events"] = [page["events"][1]]
    point = datetime(2026, 10, 20, 10, tzinfo=UTC)
    assert len(probe.map_pages([page], point, END).occurrences) == 1
    assert probe.map_pages([page], START, point).occurrences == []
    assert probe.map_pages([fixture("events_1")], END, END + timedelta(days=1)).occurrences == []


@pytest.mark.parametrize("change", ["missing_start", "naive_time", "duplicate", "missing_id"])
def test_mapping_rejects_invalid_or_duplicate_occurrence(change):
    page = fixture("events_2")
    page["events"] = [page["events"][1]]
    row = page["events"][0]
    if change == "missing_start":
        row.pop("start")
    elif change == "naive_time":
        row["start"]["dateTime"] = "2026-10-20T12:00:00"
    elif change == "missing_id":
        row.pop("id")
    else:
        page["events"].append(deepcopy(row))
    with pytest.raises(probe.ProbeError, match="^provider_unavailable$"):
        probe.map_pages([page], START, END)


async def test_pagination_preserves_every_filter():
    calls = []
    filters = {"calendarId": "work@example.org", "startTime": START.isoformat(),
               "endTime": END.isoformat(), "pageSize": 250, "timeZone": "UTC"}

    async def call(tool, arguments):
        calls.append((tool, arguments))
        return fixture("events_2" if arguments.get("pageToken") else "events_1")

    result = await probe.pages(call, "list_events", filters)
    assert len(probe.map_pages(result, START, END).occurrences) == 4
    assert calls == [("list_events", filters), ("list_events", {
        **filters, "pageToken": "synthetic-events-page-2",
    })]
    assert "pageToken" not in filters


@pytest.mark.parametrize("kind,cap", [("list_events", 40), ("list_calendars", 10)])
async def test_page_caps_fail_without_returning_partial_list(kind, cap):
    count = 0

    async def call(tool, arguments):
        nonlocal count
        count += 1
        return {"events" if kind == "list_events" else "calendars": [], "nextPageToken": str(count)}

    with pytest.raises(probe.ProbeError):
        await probe.pages(call, kind, {})
    assert count == cap


@pytest.mark.parametrize("page", [{}, {"events": None}, {"events": [None]},
                                   {"events": [], "nextPageToken": 42}])
async def test_malformed_pages_fail(page):
    async def call(tool, arguments):
        return page

    with pytest.raises(probe.ProbeError):
        await probe.pages(call, "list_events", {})
    with pytest.raises(probe.ProbeError):
        probe.map_pages([fixture("malformed")], START, END)


async def test_occurrence_cap_cycle_and_provider_failure():
    async def too_many(tool, arguments):
        return {"events": [{}] * 10_001}

    async def cyclic(tool, arguments):
        return {"events": [], "nextPageToken": "same"}

    async def unavailable(tool, arguments):
        raise RuntimeError("test-only-private-value")

    for call in (too_many, cyclic):
        with pytest.raises(probe.ProbeError):
            await probe.pages(call, "list_events", {})
    with pytest.raises(RuntimeError):
        await probe.pages(unavailable, "list_events", {})


@pytest.mark.parametrize("tool", ["get_event", "create_event", "update_event", "delete_event", "respond_to_event"])
async def test_allowlist_rejects_before_rest_or_pagination(tool, monkeypatch):
    from api.mail import connectors

    async def forbidden(*args):
        pytest.fail("REST must not be called")

    monkeypatch.setattr(connectors, "_call_tool", forbidden)
    with pytest.raises(probe.ProbeError):
        await probe.live_call(tool, {})
    with pytest.raises(probe.ProbeError):
        await probe.pages(forbidden, tool, {})


async def test_live_read_uses_low_level_helper_without_widening_mail_allowlist(monkeypatch):
    from api.mail import connectors

    async def fake(connector, tool, arguments):
        assert (connector, tool, arguments) == ("google_calendar", "list_events", {"pageSize": 1})
        return '{"events": []}'

    monkeypatch.setattr(connectors, "_call_tool", fake)
    assert await probe.live_call("list_events", {"pageSize": 1}) == {"events": []}
    assert not probe.READ_TOOLS.intersection(connectors.READ_TOOLS | connectors.WRITE_TOOLS)


async def test_offline_summary_and_redaction():
    result = await probe.offline()
    assert result["mapped_occurrences"] == 4
    assert result["moved_identity_retained"] is True
    assert result["malformed_rejected"] is True
    assert result["events"]["pages"] == 2
    assert result["calendars"]["count"] == 2
    page = fixture("events_1")
    page["private-key@example.org"] = "private-value"
    page["events"][0]["private-key@example.org"] = "private-value"
    page["events"][0]["updated"] = "private-date-text"
    output = json.dumps(probe.shape([page], "events"))
    for private in ("example.org", "Werkstatt", "synthetic", "private", "2026"):
        assert private not in output
    assert "####-##-##T##:##:##+##:##" in output
    assert probe.shape([page], "events")["unknown_key_count"] == 2


@pytest.mark.parametrize("arguments", [
    ["--live"], ["--calendar-id", "private-id"],
    ["--live", "--calendar-id", "private-id", "--start", "private-date", "--end", "other-private-date"],
    ["--tool", "delete_event"], ["--page-size", "private-value"],
])
def test_cli_requires_explicit_valid_live_arguments(arguments, monkeypatch, capsys):
    async def forbidden(*args):
        pytest.fail("Provider must not be called")

    monkeypatch.setattr(probe, "live_call", forbidden)
    with pytest.raises(SystemExit) as exc:
        probe.main(arguments)
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "private" not in captured.err + captured.out
    assert "delete_event" not in captured.err + captured.out


def test_cli_redacts_provider_errors(monkeypatch, capsys):
    async def unavailable(*args):
        raise RuntimeError("test-only-private-value")

    monkeypatch.setattr(probe, "live_call", unavailable)
    assert probe.main(["--live", "--calendar-id", "work@example.org",
                       "--start", "2026-10-01T00:00:00Z", "--end", "2026-11-01T00:00:00Z"]) == 1
    assert capsys.readouterr().out.strip() == '{"error": "provider_unavailable"}'
