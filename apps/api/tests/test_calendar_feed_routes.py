"""Privileged setup must never echo secret addresses, including schema failures."""

import pytest


@pytest.mark.parametrize("change", [{"timezone": []}, {"url": ["https://calendar.example/test-only"]},
                                    {"url": "http://calendar.example/test-only"},
                                    {"context_id": "other"}, {"name": "https://calendar.example/test-only"}])
def test_invalid_configuration_is_redacted(client, caplog, change):
    body = {"name": "Example", "url": "https://calendar.example/test-only", "timezone": "UTC", **change}
    response = client.post("/api/v1/calendar/feeds/validate", json=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "calendar_feed_invalid"}
    assert "calendar.example" not in response.text + caplog.text


def test_preview_redaction_and_server_context(client, monkeypatch, caplog):
    from datetime import UTC, datetime
    from api.calendar import feeds
    async def validate(config):
        assert config["url"] == "https://calendar.example/test-only"
        assert "context_id" not in config
        return dict(validation_id="test-only", name=config["name"], coverage_start=datetime(2026, 1, 1, tzinfo=UTC),
                    coverage_end=datetime(2026, 2, 1, tzinfo=UTC), expires_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
                    occurrence_count=2, format_issues=[])
    monkeypatch.setattr(feeds, "validate", validate)
    response = client.post("/api/v1/calendar/feeds/validate", json={"name": "Example", "url": "webcal://calendar.example/test-only", "timezone": "UTC"})
    assert response.status_code == 200 and response.json()["occurrence_count"] == 2
    assert response.headers["cache-control"] == "no-store"
    assert "calendar.example" not in response.text + caplog.text
