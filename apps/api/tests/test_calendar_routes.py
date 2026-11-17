"""Calendar read scope and window validation."""

from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_source import CalendarSource


def test_stale_depends_on_snapshot_completeness_not_age(client, monkeypatch):
    from datetime import UTC, datetime
    from db.accessors import calendar_source, calendar_sync_state
    from db.models.calendar_sync_state import CalendarSyncState

    source = CalendarSource(provider="synthetic", connection_ref="example", external_id="example", name="Example", timezone="UTC")
    state = CalendarSyncState(source_id=source.id, last_success_at=datetime(2020, 1, 1, tzinfo=UTC), incomplete=False)
    async def sources():
        return [source]
    async def get(_):
        return state
    monkeypatch.setattr(calendar_source, "list_all", sources)
    monkeypatch.setattr(calendar_sync_state, "get", get)
    assert client.get("/api/v1/calendar/sources").json()[0]["stale"] is False
    state.incomplete = True
    assert client.get("/api/v1/calendar/sources").json()[0]["stale"] is True
    state.last_success_at = None
    state.incomplete = False
    assert client.get("/api/v1/calendar/sources").json()[0]["stale"] is True


def test_occurrence_window_and_cursor_validation(client):
    assert client.get("/api/v1/calendar/occurrences", params={"from": "2026-01-01", "to": "2026-04-02"}).status_code == 422
    assert client.get("/api/v1/calendar/occurrences", params={"from": "2026-01-01", "to": "2026-01-02", "cursor": "!!!"}).status_code == 422


def test_inactive_and_unknown_sources_are_not_visible(client, monkeypatch):
    from db.accessors import calendar_source, calendar_occurrence
    source = CalendarSource(provider="synthetic", connection_ref="example", external_id="example", name="Example", timezone="UTC", is_active=False)
    async def get(source_id):
        return source if source_id == source.id else None
    async def visible(occurrence_id):
        return None
    monkeypatch.setattr(calendar_source, "get", get)
    monkeypatch.setattr(calendar_occurrence, "get_visible", visible)
    for source_id in (source.id, "unknown"):
        response = client.get("/api/v1/calendar/occurrences", params={"from": "2026-01-01", "to": "2026-01-02", "source_ids": [source_id]})
        assert response.status_code == 404
    assert client.get("/api/v1/calendar/occurrences/unknown").status_code == 404


def test_page_cursor(client, monkeypatch):
    from datetime import date
    from db.accessors import calendar_occurrence
    rows = [CalendarOccurrence(source_id="example", event_id="event", external_id=str(i),
                               start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)) for i in range(2)]
    async def page_visible(**kwargs):
        if kwargs["after"]:
            assert kwargs["after"] == (calendar_occurrence.sort_key(rows[0]), rows[0].id)
            return rows[1:]
        return rows
    monkeypatch.setattr(calendar_occurrence, "page_visible", page_visible)
    params = {"from": "2026-01-01", "to": "2026-01-02", "limit": 1}
    page = client.get("/api/v1/calendar/occurrences", params=params)
    assert page.status_code == 200 and len(page.json()["items"]) == 1
    params["cursor"] = page.json()["next_cursor"]
    page = client.get("/api/v1/calendar/occurrences", params=params)
    assert page.status_code == 200 and page.json()["next_cursor"] is None


def test_point_response_has_equal_instants(client, monkeypatch):
    from datetime import UTC, datetime
    from db.accessors import calendar_occurrence
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    point = CalendarOccurrence(source_id="example", event_id="event", external_id="point",
                               start_at=instant, end_at=instant, timezone="UTC")
    async def page_visible(**kwargs):
        return [point]
    monkeypatch.setattr(calendar_occurrence, "page_visible", page_visible)
    response = client.get("/api/v1/calendar/occurrences", params={"from": "2026-01-01", "to": "2026-01-02"})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["start_at"] == item["end_at"] == "2026-01-01T00:00:00Z"


def test_several_sources_are_checked_and_passed(client, monkeypatch):
    from db.accessors import calendar_occurrence, calendar_source
    active = {name: CalendarSource(provider="synthetic", connection_ref="example", external_id=name, name=name,
                                   timezone="UTC") for name in ("a", "b")}
    by_id = {source.id: source for source in active.values()}
    async def get(source_id):
        return by_id.get(source_id)
    seen = {}
    async def page_visible(**kwargs):
        seen.update(kwargs)
        return []
    monkeypatch.setattr(calendar_source, "get", get)
    monkeypatch.setattr(calendar_occurrence, "page_visible", page_visible)
    ids = [active["a"].id, active["b"].id, active["a"].id]
    params = {"from": "2026-01-01", "to": "2026-01-02", "source_ids": ids}
    assert client.get("/api/v1/calendar/occurrences", params=params).status_code == 200
    assert seen["source_ids"] == ids[:2]
    params["source_ids"] = [active["a"].id, "unknown"]
    assert client.get("/api/v1/calendar/occurrences", params=params).status_code == 404
    params["source_ids"] = [f"s{i}" for i in range(51)]
    assert client.get("/api/v1/calendar/occurrences", params=params).status_code == 422


def test_cursor_needs_time_and_id(client):
    import base64
    from uuid import uuid4
    def enc(text):
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    params = {"from": "2026-01-01", "to": "2026-01-02"}
    for bad in (str(uuid4()), f"2026-01-01T00:00:00|{uuid4()}", "2026-01-01T00:00:00+00:00|not-an-id"):
        assert client.get("/api/v1/calendar/occurrences", params={**params, "cursor": enc(bad)}).status_code == 422
