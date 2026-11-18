"""Google discovery stays browser-only and never accepts a client connection identity."""

import json
from pathlib import Path

import pytest
from db.models.calendar_source import CalendarSource

from api.calendar import google
from db.accessors import calendar_source, calendar_sync_state

BASE = "/api/v1/calendar/connections/google"
FIXTURES = Path(__file__).parent / "fixtures/google_calendar"


@pytest.fixture
def discovery(monkeypatch):
    calls = []

    async def call(tool, args):
        calls.append((tool, args))
        if tool == "list_events":
            return {"summary": "work@example.org", "events": []}
        return json.loads((FIXTURES / ("calendars_2.json" if args.get("pageToken") else "calendars_1.json")).read_text())

    async def state(identifier):
        return None

    monkeypatch.setattr(google, "live_call", call)
    monkeypatch.setattr(calendar_sync_state, "get", state)
    return calls


def test_list_links_only_current_identity_and_redacts_connection_data(client, monkeypatch, discovery):
    row = CalendarSource(provider="google", connection_ref="unused", external_id="work@example.org", name="Example", timezone="UTC")

    async def connected(provider, ref):
        assert provider == "google" and ref.startswith("google_calendar#") and "example.org" not in ref
        return [row]

    monkeypatch.setattr(calendar_source, "list_connection", connected)
    response = client.get(BASE + "/calendars")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"calendars": [
        {"id": "work@example.org", "name": "Werkstatt", "timezone": "Europe/Berlin", "access": None, "source_id": row.id},
        {"id": "garden@example.org", "name": "Garten", "timezone": "UTC", "access": None, "source_id": None},
    ]}
    assert "description" not in response.text and "connection_ref" not in response.text
    assert [tool for tool, _ in discovery] == ["list_events", "list_calendars", "list_calendars", "list_events"]


def test_unknown_id_is_rejected_before_any_sources_are_created(client, monkeypatch, discovery):
    async def forbidden(*args, **kwargs):
        pytest.fail("unknown selection must not touch source storage")

    monkeypatch.setattr(calendar_source, "connect_google", forbidden)
    response = client.post(BASE, json={"calendar_ids": ["work@example.org", "unknown@example.org"]})
    assert response.status_code == 422 and response.json() == {"detail": "calendar_unknown"}
    assert response.headers["cache-control"] == "no-store"


def test_connect_passes_only_server_metadata_and_returns_public_sources(client, monkeypatch, discovery):
    async def connect(ref, selected, **kwargs):
        assert ref.startswith("google_calendar#")
        assert selected == [{"id": "garden@example.org", "name": "Garten", "timezone": "UTC", "access": None}]
        assert kwargs["interval"] == 5
        return [CalendarSource(provider="google", connection_ref=ref, external_id=selected[0]["id"], name=selected[0]["name"], timezone="UTC", capabilities_json='["read"]')]

    monkeypatch.setattr(calendar_source, "connect_google", connect)
    response = client.post(BASE, json={"calendar_ids": ["garden@example.org"]})
    assert response.status_code == 200
    assert response.json()[0]["capabilities"] == ["read"]
    assert "connection_ref" not in response.text and "external_id" not in response.text


@pytest.mark.parametrize("body", [{"calendar_ids": []}, {"calendar_ids": ["a"] * 2},
    {"calendar_ids": [str(i) for i in range(21)]}, {"calendar_ids": ["a"], "connection_ref": "private-value"},
    {"calendar_ids": [None]}, {"calendar_ids": [""]}])
def test_invalid_body_is_redacted_before_provider_call(client, monkeypatch, body):
    async def forbidden(*args):
        pytest.fail("invalid body reached provider")

    monkeypatch.setattr(google, "calendars", forbidden)
    response = client.post(BASE, json=body)
    assert response.status_code == 422 and response.json() == {"detail": "calendar_invalid"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("code,status,detail", [("reconnect_required", 409, "google_calendar_not_connected"),
    ("calendar_unavailable", 502, "provider_unavailable"), ("provider_unavailable", 502, "provider_unavailable")])
@pytest.mark.parametrize("method", ["get", "post"])
def test_discovery_errors_are_fixed_and_not_cached(client, monkeypatch, code, status, detail, method):
    async def unavailable():
        raise google.GoogleError(code)

    monkeypatch.setattr(google, "calendars", unavailable)
    response = client.get(BASE + "/calendars") if method == "get" else client.post(BASE, json={"calendar_ids": ["work@example.org"]})
    assert response.status_code == status and response.json() == {"detail": detail}
    assert response.headers["cache-control"] == "no-store"


def test_connector_missing_maps_to_not_connected(client, monkeypatch):
    from api.mail import connectors
    import httpx

    async def missing(*args):
        request = httpx.Request("POST", "https://provider.example/test")
        raise httpx.HTTPStatusError("private-value", request=request, response=httpx.Response(404, request=request))

    monkeypatch.setattr(connectors, "_call_tool", missing)
    response = client.get(BASE + "/calendars")
    assert response.status_code == 409 and response.json() == {"detail": "google_calendar_not_connected"}


async def test_identity_change_during_discovery_fails(monkeypatch):
    count = 0

    async def call(tool, args):
        nonlocal count
        if tool == "list_calendars":
            return {"calendars": []}
        count += 1
        return {"summary": "work@example.org" if count == 1 else "other@example.org", "events": []}

    monkeypatch.setattr(google, "live_call", call)
    with pytest.raises(google.GoogleError, match="^reconnect_required$"):
        await google.calendars()
