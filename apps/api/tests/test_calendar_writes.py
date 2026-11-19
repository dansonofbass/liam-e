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
    from db.accessors import calendar_source, calendar_occurrence, calendar_write, calendar_index_write, calendar_sync_state
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
                        mode="done", matches=None, dispatch_ok=True, gone=False, calendar_gone=False)
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
            if s.calendar_gone: return "Google Calendar request failed (HTTP 404, reason notFound, not applied): Example."
            return json.dumps({"events": s.matches if s.matches is not None else [s.event]})
        if tool == "get_event":
            return "Google Calendar request failed (HTTP 404, reason notFound, not applied): Example." if s.gone else json.dumps(s.event)
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
    async def sync_state(_): return SimpleNamespace(data_revision=0)
    monkeypatch.setattr(calendar_sync_state, "get", sync_state)
    monkeypatch.setattr(calendar_source, "get", source_get)
    monkeypatch.setattr(calendar_occurrence, "get_visible", occurrence_get)
    monkeypatch.setattr(calendar_write, "claim", claim)
    monkeypatch.setattr(calendar_write, "get", get)
    monkeypatch.setattr(calendar_write, "finish", finish)
    monkeypatch.setattr(calendar_write, "expire_running", expire)
    async def mark_dispatch(identifier, *, request_json):
        row = s.records[identifier]
        if not s.dispatch_ok:
            row.status = "unknown"  # Expired by a concurrent read before dispatch.
        if row.status != "running":
            return False
        row.started_at = datetime.now(UTC)
        row.request_json = request_json
        return True
    monkeypatch.setattr(calendar_write, "mark_dispatch", mark_dispatch)
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


async def test_seed_write_changes_index_without_connector(state):
    from api.mail.seed_ids import seed_id
    state.source.id = seed_id("calendar", "work")
    result = await writes.execute(request(source_id=state.source.id))
    assert result.status == "done"
    assert not state.calls
    assert state.applied[0]["upsert"][1].external_id.startswith("seed-")


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


def age(state, write_id, minutes):
    state.records[write_id].started_at = datetime.now(UTC) - timedelta(minutes=minutes)


async def test_timeout_unknown_then_check_not_applied(state):
    state.mode = "timeout"
    result = await writes.execute(request())
    state.matches = []
    age(state, result.write_id, 6)
    assert (await writes.check(result.write_id)).status == "not_applied"


async def test_check_young_create_without_events_stays_unknown(state):
    # The connector may still be working after the client timeout, or search may lag.
    state.mode = "timeout"
    result = await writes.execute(request())
    state.matches = []
    assert (await writes.check(result.write_id)).status == "unknown"
    assert (await writes.get(result.write_id)).status == "unknown"


async def test_check_renamed_recent_event_stays_unknown(state):
    state.mode = "timeout"
    result = await writes.execute(request())
    state.matches = [{**state.event, "summary": "Renamed in Google"}]
    age(state, result.write_id, 6)
    assert (await writes.check(result.write_id)).status == "unknown"


async def test_check_create_lists_the_window_without_free_text(state):
    state.mode = "timeout"
    result = await writes.execute(request(title="C++ ✓"))
    state.event["summary"] = "C++ ✓"
    assert (await writes.check(result.write_id)).status == "done"
    listing = [args for tool, args in state.calls if tool == "list_events" and "calendarId" in args]
    assert listing and all("fullText" not in args for args in listing)


@pytest.mark.parametrize("created", [timedelta(minutes=-2), timedelta(seconds=-1), timedelta(0), None])
async def test_check_create_never_adopts_an_event_not_created_after_dispatch(state, created):
    # An identical appointment made shortly before the write, or one without a creation
    # time, keeps the outcome open but never proves that this write created it.
    state.mode = "timeout"
    result = await writes.execute(request())
    dispatched = next(iter(state.records.values())).started_at
    if created is None: state.event.pop("created")
    else: state.event["created"] = (dispatched + created).isoformat()
    outcome = await writes.check(result.write_id)
    assert outcome.status == "unknown" and outcome.occurrence_id is None
    assert not state.applied


async def test_legacy_claim_without_dispatch_evidence_cannot_adopt_a_match(state):
    state.mode = "timeout"
    result = await writes.execute(request())
    record = state.records[result.write_id]
    bound = json.loads(record.request_json)
    bound.pop("dispatched", None)
    record.request_json = json.dumps(bound)
    outcome = await writes.check(result.write_id)
    assert outcome.status == "unknown" and outcome.occurrence_id is None
    assert not state.applied


async def test_check_reconciles_after_the_calendar_became_read_only(state):
    # Reading back needs read access only; a lost permission must not strand the outcome.
    state.mode = "timeout"
    result = await writes.execute(request())
    state.source.capabilities_json = '["read"]'
    assert (await writes.check(result.write_id)).status == "done"


async def test_retry_returns_existing_outcome_when_calendar_became_read_only(state):
    command = request()
    first = await writes.execute(command)
    state.source.capabilities_json = '["read"]'

    assert first.status == "done"
    assert (await writes.execute(command)) == first
    assert sum(tool == "create_event" for tool, _ in state.calls) == 1


@pytest.mark.parametrize("created", [None, "invalid"])
async def test_check_create_stays_unknown_with_an_indeterminate_competing_match(state, created):
    state.mode = "timeout"
    result = await writes.execute(request())
    state.matches = [state.event, {**state.event, "id": "synthetic-other", "created": created}]

    assert (await writes.check(result.write_id)).status == "unknown"
    assert not state.applied


async def test_expired_claim_before_dispatch_sends_nothing(state):
    state.dispatch_ok = False
    state.event["created"] = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    result = await writes.execute(request())
    assert result.status == "not_applied" and result.occurrence_id is None
    assert not state.applied
    assert not any(tool == "create_event" for tool, _ in state.calls)


async def test_seed_write_failure_ends_the_claim(state, monkeypatch):
    from api.mail.seed_ids import seed_id
    from db.accessors import calendar_index_write
    async def broken(**_): raise RuntimeError("test-only")
    monkeypatch.setattr(calendar_index_write, "apply", broken)
    state.source.id = seed_id("calendar", "work")
    result = await writes.execute(request(source_id=state.source.id))
    assert result.status == "failed" and result.error_code == "calendar_unavailable"


async def test_create_resolution_matches_identity_fields_not_optional_text(state):
    state.mode = "timeout"
    result = await writes.execute(request(description="Example description", location="Example room"))
    state.event.pop("description", None)
    state.event.pop("location", None)
    assert (await writes.check(result.write_id)).status == "done"


async def test_check_ambiguous_create_stays_unknown(state):
    state.mode = "timeout"
    result = await writes.execute(request())
    state.matches = [state.event, {**state.event, "id": "synthetic-other"}]
    assert (await writes.check(result.write_id)).status == "unknown"


@pytest.mark.parametrize("calendar_gone,expected", [(False, "done"), (True, "unknown")])
async def test_check_delete_404_needs_a_reachable_calendar(state, calendar_gone, expected):
    # A 404 also answers for a calendar that was deleted or unshared; only a reachable
    # calendar makes the missing event a completed delete.
    state.mode = "timeout"
    result = await writes.execute(request("delete"))
    state.gone, state.calendar_gone = True, calendar_gone
    assert (await writes.check(result.write_id)).status == expected


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


@pytest.mark.parametrize("changes,valid", [
    (dict(start_date="2026-01-01", end_date="2027-01-02"), True),   # 366 days
    (dict(start_date="2026-01-01", end_date="2027-01-03"), False),  # 367 days
    (dict(start_local="2026-12-01T09:00", end_local="2026-12-15T09:00", timezone="UTC"), True),
    (dict(start_local="2026-12-01T09:00", end_local="2026-12-15T09:01", timezone="UTC"), False),
])
def test_duration_limits(changes, valid):
    base = dict(write_id=uuid4(), operation="create", source_id="synthetic-source", title="Example")
    if valid:
        writes.WriteRequest(**base, **changes)
    else:
        with pytest.raises(writes.WriteError, match="calendar_time_invalid"):
            writes.WriteRequest(**base, **changes)


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
