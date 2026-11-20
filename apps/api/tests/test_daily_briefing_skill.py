"""Isolated tests for the multi-domain collect_daily_briefing skill tool."""

from datetime import UTC, date, datetime
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState
from db.models.mail_insight import MailInsight
from db.models.mail_message import MailMessage

from api.skills import briefing

pytestmark = pytest.mark.anyio


def _ctx(**overrides):
    defaults = dict(
        conversation_id="conv-1",
        account_id=None,
        today=date(2026, 11, 21),
        account_ids=["acc-1"],
        calendar_source_ids=["cal-1"],
        calendar_timezone="Europe/Berlin",
        task_scope={"source": "all"},
    )
    defaults.update(overrides)
    return NS(**defaults)


async def test_collect_daily_briefing_merges_authorized_calendar_tasks_and_mail_deadlines(monkeypatch):
    source = CalendarSource(
        id="cal-1",
        provider="ics",
        connection_ref="synthetic-ref",
        external_id="cal-1",
        name="Privat",
        timezone="Europe/Berlin",
        capabilities_json='["read"]',
    )
    state = CalendarSyncState(
        source_id="cal-1",
        incomplete=False,
        coverage_start=datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
        coverage_end=datetime(2026, 12, 1, 0, 0, tzinfo=UTC),
        last_success_at=datetime(2026, 11, 21, 7, 0, tzinfo=UTC),
    )
    occ = CalendarOccurrence(
        id="occ-1",
        source_id="cal-1",
        event_id="evt-1",
        external_id="evt-1",
        title="Team Sync",
        start_at=datetime(2026, 11, 21, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 11, 21, 10, 0, tzinfo=UTC),
        timezone="Europe/Berlin",
    )
    monkeypatch.setattr(briefing.calendar_tools.calendar_source, "catalog", AsyncMock(return_value=[(source, state)]))
    monkeypatch.setattr(briefing.calendar_tools.calendar_occurrence, "page_visible", AsyncMock(return_value=[occ]))

    async def fake_task_read(name, args, scope, account_ids):
        assert name == "search_tasks"
        assert scope == {"source": "all"}
        assert account_ids == ["acc-1"]
        return {
            "read_only": True,
            "next_cursor": None,
            "untrusted_task_data": {
                "series": [
                    {
                        "series_id": "ts-1",
                        "title": "Steuerunterlagen prüfen",
                        "version": 2,
                        "source_account_id": "acc-1",
                        "source_message_id": None,
                        "complete": True,
                        "next_occurrence_cursor": None,
                        "occurrences": [
                            {"id": "to-1", "version": 1, "due_local": "2026-11-21T11:00", "status": "open"},
                            {"id": "to-old", "version": 1, "due_local": "2026-11-19", "status": "open"},
                        ],
                    }
                ]
            },
        }

    monkeypatch.setattr(briefing.task_chat, "read", fake_task_read)

    due_mail = MailMessage(
        id="mail-1",
        account_id="acc-1",
        provider_uid="1",
        subject="Vertrag unterschreiben",
        sender="Alice <alice@example.org>",
        internal_date=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        is_read=False,
        is_flagged=True,
    )
    monkeypatch.setattr(briefing.mail_message, "list_page", AsyncMock(return_value=[due_mail]))
    monkeypatch.setattr(
        briefing.mail_insight,
        "get_for_messages",
        AsyncMock(
            return_value={
                "mail-1": MailInsight(
                    message_id="mail-1",
                    points_json='["Rücksendung bis 21.11."]',
                    deadline=date(2026, 11, 21),
                    needs_reply=True,
                    followups_json="[]",
                )
            }
        ),
    )

    outcome = await briefing.collect_daily_briefing({}, _ctx())
    data = json.loads(outcome.content)

    assert data["read_only"] is True
    assert data["date"] == "2026-11-21"
    assert outcome.proposal_message is None
    assert outcome.calendars == [{"source_id": "cal-1", "occurrence_id": "occ-1"}]
    assert "synthetic-ref" not in outcome.content

    cal = data["untrusted_daily_briefing"]["calendar"]
    assert cal["available"] is True and cal["complete"] is True
    assert [item["title"] for item in cal["occurrences"]] == ["Team Sync"]

    tasks = data["untrusted_daily_briefing"]["tasks"]
    assert tasks["available"] is True and tasks["complete"] is True
    assert [t["occurrence_id"] for t in tasks["due_on_date"]] == ["to-1"]
    assert [t["occurrence_id"] for t in tasks["overdue"]] == ["to-old"]

    mails = data["untrusted_daily_briefing"]["mails"]
    assert mails["available"] is True and mails["complete"] is True
    assert [m["message_id"] for m in mails["due_or_overdue_deadlines"]] == ["mail-1"]
    assert data["coverage"]["excluded_domains"] == []
    assert data["coverage"]["incomplete_domains"] == []


async def test_collect_daily_briefing_reports_excluded_and_incomplete_scopes_honestly(monkeypatch):
    monkeypatch.setattr(briefing.calendar_tools.calendar_source, "catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(briefing.calendar_tools.calendar_occurrence, "page_visible", AsyncMock(return_value=[]))
    list_page = AsyncMock()
    monkeypatch.setattr(briefing.mail_message, "list_page", list_page)

    outcome = await briefing.collect_daily_briefing(
        {},
        _ctx(account_ids=[], calendar_source_ids=[], task_scope={"source": "none"}),
    )
    data = json.loads(outcome.content)
    list_page.assert_not_awaited()
    assert data["coverage"]["excluded_domains"] == ["calendar", "tasks", "mails"]
    assert data["untrusted_daily_briefing"]["calendar"]["reason"] == "no_readable_sources"
    assert data["untrusted_daily_briefing"]["tasks"]["reason"] == "task_scope_none"
    assert data["untrusted_daily_briefing"]["mails"]["reason"] == "no_granted_accounts"
    assert data["coverage"]["calendar_complete"] is False
    assert data["coverage"]["tasks_complete"] is False
    assert data["coverage"]["mails_complete"] is False


async def test_collect_daily_briefing_rejects_invalid_window_and_revoked_calendar(monkeypatch):
    bad = await briefing.collect_daily_briefing({"date": "not-a-date"}, _ctx())
    assert json.loads(bad.content) == {"error": "briefing_window_invalid"}

    bad_focus = await briefing.collect_daily_briefing({}, _ctx(account_id="acc-other"))
    assert json.loads(bad_focus.content) == {"error": "account_out_of_scope"}

    monkeypatch.setattr(briefing.calendar_tools.calendar_source, "catalog", AsyncMock(return_value=[]))
    revoked = await briefing.collect_daily_briefing({}, _ctx(calendar_source_ids=["cal-paused"]))
    assert json.loads(revoked.content) == {"error": "calendar_scope_revoked"}
