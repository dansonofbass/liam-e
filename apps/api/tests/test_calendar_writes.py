"""Calendar write service with an in-memory index and a fake connector only."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from api.calendar import writes


@pytest.fixture
def state(monkeypatch):
    from api.mail import connectors
    from db.accessors import calendar_source, calendar_occurrence, calendar_write, calendar_index_write
    from db.models.calendar_source import CalendarSource
    from db.models.calendar_occurrence import CalendarOccurrence
    import hashlib

    ref = "google_calendar#" + hashlib.sha256(b"google_calendar:synthetic-primary").hexdigest()[:16]
    source = CalendarSource(id="synthetic-source", provider="google", connection_ref=ref,
        external_id="synthetic-calendar", name="Example", timezone="UTC", capabilities_json='["read","write"]')
    occurrence = CalendarOccurrence(id="synthetic-occurrence", source_id=source.id, event_id="synthetic-event",
        external_id="synthetic-event", title="Example", start_at=datetime(2026, 12, 5, 9, tzinfo=UTC),
        end_at=datetime(2026, 12, 5, 10, tzinfo=UTC), timezone="UTC", editable=True)
    event = {"id": "synthetic-event", "summary": "Example", "start": {"dateTime": "2026-12-05T09:00:00Z"},
        "end": {"dateTime": "2026-12-05T10:00:00Z"}, "updated": "old", "eventType": "default"}
    s = SimpleNamespace(source=source, occurrence=occurrence, event=event, records={}, calls=[], applied=[],
                        mode="done", matches=None)
    async def source_get(_): return s.source
    async def occurrence_get(_): return s.occurrence
    async def claim(row):
        if row.id in s.records:
            old = s.records[row.id]
            if old.request_hash != row.request_hash: raise calendar_write.WriteConflict()
            return old, False
        s.records[row.id] = row
        return row, True
    async def get(identifier): return s.records.get(identifier)
    async def finish(identifier, **values):
        row = s.records[identifier]
        for key, value in values.items(): setattr(row, key, value)
        if row.status in {"done", "failed", "not_applied"}: row.request_json = None
        return row
    async def expire(identifier, *, before):
        row = s.records.get(identifier)
        if row and row.status == "running" and row.started_at < before: row.status = "unknown"
        return row
    async def apply(**kwargs):
        s.applied.append(kwargs)
        return True
    async def fake(connector, tool, arguments, **kwargs):
        s.calls.append((tool, deepcopy(arguments)))
        if tool == "list_events":
            if "calendarId" not in arguments:
                return json.dumps({"summary": "synthetic-primary", "events": []})
            return json.dumps({"events": s.matches if s.matches is not None else [s.event]})
        if tool == "get_event": return json.dumps(s.event)
        assert arguments["notificationLevel"] == "NONE"
        assert kwargs["timeout"] == 30
        if s.mode == "403":
            return "Google Calendar request failed (HTTP 403, reason forbidden, not applied): Example."
        if s.mode == "missing_id": return '{}'
        if tool == "delete_event": s.event["status"] = "cancelled"
        else:
            for key in ("summary", "location", "description"):
                if key in arguments: s.event[key] = arguments[key]
            for key, name in (("startTime", "start"), ("endTime", "end")):
                if key in arguments:
                    s.event[name] = ({"date": arguments[key][:10]} if arguments.get("allDay") else {"dateTime": arguments[key]})
        s.event["updated"] = "new"
        s.event["created"] = datetime.now(UTC).isoformat()
        if s.mode == "timeout": raise httpx.ReadTimeout("test-only")
        return json.dumps(s.event)
    monkeypatch.setattr(calendar_source, "get", source_get)
    monkeypatch.setattr(calendar_occurrence, "get_visible", occurrence_get)
    monkeypatch.setattr(calendar_write, "claim", claim)
    monkeypatch.setattr(calendar_write, "get", get)
    monkeypatch.setattr(calendar_write, "finish", finish)
    monkeypatch.setattr(calendar_write, "expire_running", expire)
    async def find(source_id, external_id): return s.occurrence
    monkeypatch.setattr(calendar_index_write, "find", find)
    monkeypatch.setattr(calendar_index_write, "apply", apply)
    monkeypatch.setattr(connectors, "_call_tool", fake)
    return s


def request(operation="create", **changes):
    values = dict(write_id=uuid4(), operation=operation, source_id="synthetic-source")
    if operation == "create": values.update(title="Example", start_local="2026-12-05T09:00", end_local="2026-12-05T10:00", timezone="UTC")
    else: values.update(occurrence_id="synthetic-occurrence", expected_revision="old")
    if operation == "update": values["title"] = "Changed"
    return writes.WriteRequest(**{**values, **changes})


async def test_create_done_updates_index(state):
    assert (await writes.execute(request())).status == "done"
    assert len(state.applied) == 1


async def test_same_write_id_returns_first_outcome_without_second_call(state):
    req = request()
    await writes.execute(req)
    await writes.execute(req)
    assert sum(t == "create_event" for t, _ in state.calls) == 1


async def test_same_write_id_other_payload_conflicts(state):
    req = request()
    await writes.execute(req)
    with pytest.raises(writes.WriteError, match="calendar_write_conflict"):
        await writes.execute(req.model_copy(update={"title": "Other"}))


async def test_update_changed_revision_not_applied_with_current(state):
    state.event["updated"] = "other"
    result = await writes.execute(request("update"))
    assert result.status == "not_applied" and result.current.revision == "other"
    assert result.error_code == "calendar_event_changed"
    assert not any(t == "update_event" for t, _ in state.calls)


async def test_update_sends_only_changed_fields(state):
    await writes.execute(request("update"))
    args = next(a for t, a in state.calls if t == "update_event")
    assert set(args) == {"calendarId", "eventId", "summary", "notificationLevel"}


async def test_clear_location_sends_empty_string(state):
    await writes.execute(request("update", location=""))
    assert next(a for t, a in state.calls if t == "update_event")["location"] == ""


async def test_delete_done_removes_occurrence(state):
    assert (await writes.execute(request("delete"))).status == "done"
    assert state.applied[0]["delete_external_id"] == "synthetic-event"


@pytest.mark.parametrize("extra", [{"recurringEventId": "synthetic-series"}, {"attendees": [{}]}, {"organizer": {"self": False}}])
async def test_not_editable_series_guests_organizer_refused(state, extra):
    state.event.update(extra)
    assert (await writes.execute(request("update"))).error_code == "calendar_event_not_editable"


async def test_source_without_write_capability_refused(state):
    state.source.capabilities_json = '["read"]'
    with pytest.raises(writes.WriteError, match="calendar_not_writable"): await writes.execute(request())
    assert not state.calls


async def test_inactive_source_refused(state):
    state.source.is_active = False
    with pytest.raises(writes.WriteError, match="calendar_unavailable"): await writes.execute(request())


async def test_identity_changed_reconnect_required(state):
    state.source.connection_ref = "other"
    assert (await writes.execute(request())).error_code == "reconnect_required"


async def test_timeout_unknown_then_check_done_single_match(state):
    state.mode = "timeout"
    result = await writes.execute(request())
    assert result.status == "unknown"
    assert (await writes.check(result.write_id)).status == "done"
    assert sum(t == "create_event" for t, _ in state.calls) == 1


async def test_timeout_unknown_then_check_not_applied(state):
    state.mode = "timeout"
    result = await writes.execute(request())
    state.matches = []
    assert (await writes.check(result.write_id)).status == "not_applied"


async def test_check_ambiguous_create_stays_unknown(state):
    state.mode = "timeout"
    result = await writes.execute(request())
    state.matches = [state.event, {**state.event, "id": "synthetic-other"}]
    assert (await writes.check(result.write_id)).status == "unknown"


async def test_check_delete_cancelled_is_done(state):
    state.mode = "timeout"
    result = await writes.execute(request("delete"))
    assert (await writes.check(result.write_id)).status == "done"


async def test_stale_running_reads_as_unknown(state):
    result = await writes.execute(request())
    row = state.records[result.write_id]
    row.status = "running"
    row.started_at = datetime.now(UTC) - timedelta(seconds=121)
    assert (await writes.get(result.write_id)).status == "unknown"


async def test_create_response_without_id_unknown(state):
    state.mode = "missing_id"
    assert (await writes.execute(request())).status == "unknown"


def test_nonexistent_local_time_422():
    with pytest.raises(writes.WriteError) as exc: writes.resolve_local("2026-03-29T02:30", "Europe/Berlin")
    assert exc.value.code == "calendar_time_invalid" and exc.value.status == 422


def test_ambiguous_local_time_first_offset():
    assert writes.resolve_local("2026-10-25T02:30", "Europe/Berlin").utcoffset() == timedelta(hours=2)


async def test_all_day_end_is_exclusive_midnight_utc(state):
    await writes.execute(request(start_local=None, end_local=None, timezone=None, start_date="2026-12-05", end_date="2026-12-06"))
    args = next(a for t, a in state.calls if t == "create_event")
    assert args["allDay"] is True and args["endTime"] == "2026-12-06T00:00:00Z"


def test_all_day_equal_dates_refused():
    with pytest.raises((ValidationError, writes.WriteError)):
        request(start_local=None, end_local=None, timezone=None, start_date="2026-12-05", end_date="2026-12-05")


async def test_failed_403_is_write_rejected_not_reconnect(state):
    state.mode = "403"
    result = await writes.execute(request())
    assert result.status == "failed" and result.error_code == "calendar_write_rejected"


async def test_live_reads_description_as_text(state):
    state.event["description"] = "<p>Example <b>text</b></p>"
    result = await writes.live("synthetic-occurrence")
    assert result.description == "Example text" and result.description_was_html


async def test_logs_contain_no_titles(state, caplog):
    state.mode = "timeout"
    await writes.execute(request(title="Synthetic private title"))
    assert "Synthetic private title" not in caplog.text
