"""Browser write routes keep private values out of validation errors."""

from uuid import uuid4

import pytest

from api.calendar import writes


@pytest.mark.parametrize("status,code,http", [("done", None, 201), ("unknown", "calendar_write_unknown", 202),
    ("failed", "calendar_write_rejected", 403), ("not_applied", "calendar_event_changed", 409)])
def test_create_outcome_status(client, monkeypatch, status, code, http):
    async def execute(request):
        return writes.WriteOutcome(write_id=str(request.write_id), status=status, error_code=code,
            current=writes.LiveEvent(source_id="synthetic", title="Current") if code == "calendar_event_changed" else None)
    monkeypatch.setattr(writes, "execute", execute)
    response = client.post("/api/v1/calendar/events", json=dict(write_id=str(uuid4()), source_id="synthetic",
        title="Example", start_date="2026-12-05", end_date="2026-12-06"))
    assert response.status_code == http
    if code == "calendar_event_changed": assert response.json()["detail"]["current"]["title"] == "Current"


def test_extra_fields_are_redacted(client):
    response = client.post("/api/v1/calendar/events", json=dict(write_id=str(uuid4()), source_id="synthetic", title="Example",
        start_date="2026-12-05", end_date="2026-12-06", attendees="synthetic-private-text"))
    assert response.status_code == 422
    assert "synthetic-private-text" not in response.text


def test_invalid_time_is_422(client):
    response = client.post("/api/v1/calendar/events", json=dict(write_id=str(uuid4()), source_id="synthetic", title="Example",
        start_date="2026-12-05", end_date="2026-12-05"))
    assert response.status_code == 422


def test_live_and_write_reads(client, monkeypatch):
    async def live(identifier): return writes.LiveEvent(source_id="synthetic", title="Example", occurrence_id=identifier)
    async def get(identifier): return writes.WriteOutcome(write_id=identifier, status="unknown")
    monkeypatch.setattr(writes, "live", live)
    monkeypatch.setattr(writes, "get", get)
    monkeypatch.setattr(writes, "check", get)
    assert client.get("/api/v1/calendar/occurrences/synthetic/live").json()["title"] == "Example"
    assert client.get("/api/v1/calendar/writes/synthetic").status_code == 202
    assert client.post("/api/v1/calendar/writes/synthetic/check").status_code == 202
