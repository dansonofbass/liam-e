"""Write response classification without provider calls."""

import json
from pathlib import Path

import httpx
import pytest

from api.calendar import google_write

FIXTURES = Path(__file__).parent / "fixtures/google_calendar"


def test_classify_event_json():
    result = google_write.classify((FIXTURES / "write_event.json").read_text())
    assert result.kind == "event"
    assert result.event["id"] == "synthetic-event"


def test_classify_not_applied_404():
    result = google_write.classify("Google Calendar request failed (HTTP 404, reason notFound, not applied): Not Found.")
    assert (result.kind, result.status, result.reason) == ("failed", 404, "notFound")


def test_classify_validation_error_is_failed():
    result = google_write.classify("1 validation error for call[create_event]")
    assert (result.kind, result.reason) == ("failed", "schema")


@pytest.mark.parametrize("text", [
    "Google Calendar request failed (HTTP 503, reason unavailable, not applied): Example.",
    "Example", '{}', '[]', '{"id":""}', '{"id":3}',
    "Google Calendar request failed (HTTP 404, reason notFound): Example.",
])
def test_classify_5xx_or_unknown_text_is_unknown(text):
    assert google_write.classify(text).kind == "unknown"


async def test_call_refuses_other_tools(monkeypatch):
    from api.mail import connectors
    async def forbidden(*args, **kwargs):
        pytest.fail("No transport call allowed")
    monkeypatch.setattr(connectors, "_call_tool", forbidden)
    with pytest.raises(ValueError):
        await google_write.call("send_email", {})


async def test_call_timeout_is_unknown(monkeypatch):
    from api.mail import connectors
    async def fake(connector, tool, arguments, *, timeout):
        assert connector == "google_calendar" and timeout == 30
        raise httpx.ReadTimeout("test-only")
    monkeypatch.setattr(connectors, "_call_tool", fake)
    assert (await google_write.call("create_event", {})).kind == "unknown"


async def test_call_uses_fake_transport_and_fixed_timeout(monkeypatch):
    from api.mail import connectors
    async def fake(connector, tool, arguments, *, timeout):
        assert (connector, tool, arguments, timeout) == ("google_calendar", "get_event", {"eventId": "synthetic-event"}, 30)
        return json.dumps({"id": "synthetic-event"})
    monkeypatch.setattr(connectors, "_call_tool", fake)
    assert (await google_write.call("get_event", {"eventId": "synthetic-event"})).kind == "event"
