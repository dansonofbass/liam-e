#!/usr/bin/env python3
"""Read-only Google Calendar capability probe; synthetic fixtures are the default.

Run with ``bash tools/uv.sh run --no-sync python tools/calendar_google_probe.py``.
Live access requires --live and an explicit calendar/window. Nothing is persisted.
Only structural statistics leave this process, even if a provider response is malformed.
This is a probe, not a registered production adapter or an authorization mechanism.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api.calendar.adapters import Event, Occurrence, Snapshot, normalize, timed_overlaps

READ_TOOLS = frozenset({"list_calendars", "list_events"})
FIXTURES = Path(__file__).resolve().parents[1] / "apps/api/tests/fixtures/google_calendar"
Call = Callable[[str, dict[str, Any]], Awaitable[Any]]
TOP_KEYS = frozenset({
    "calendars", "nextPageToken", "summary", "description", "updated", "timeZone",
    "accessRole", "defaultReminders", "events",
})
EVENT_KEYS = frozenset({
    "id", "status", "htmlLink", "created", "updated", "summary", "description",
    "location", "creator", "organizer", "start", "end", "recurrence", "recurringEventId",
    "originalStartTime", "transparency", "visibility", "attendees", "eventType",
    "conferenceUrl", "colorId", "overrideReminders", "attachments", "guestPermissions",
    "workingLocationProperties",
})
DATE_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?\Z")


class ProbeError(ValueError):
    """A fixed public code, never a provider message or input value."""

    def __init__(self) -> None:
        super().__init__("provider_unavailable")


async def live_call(tool: str, arguments: dict[str, Any]) -> Any:
    """Keep a calendar-specific allowlist without changing the mail tool permissions."""
    if tool not in READ_TOOLS:
        raise ProbeError()
    # Lazy import: offline mode needs neither credentials nor the connector implementation.
    from api.mail.connectors import _call_tool

    return json.loads(await _call_tool("google_calendar", tool, arguments))


async def pages(call: Call, tool: str, arguments: dict[str, Any]) -> list[dict]:
    """Require every bounded page; filters remain identical when following a token."""
    if tool not in READ_TOOLS:
        raise ProbeError()
    key, cap = ("events", 40) if tool == "list_events" else ("calendars", 10)
    result: list[dict] = []
    tokens: set[str] = set()
    token = None
    count = 0
    for _ in range(cap):
        page = await call(tool, {**arguments, **({"pageToken": token} if token else {})})
        if not isinstance(page, dict) or not isinstance(page.get(key), list):
            raise ProbeError()
        if any(not isinstance(item, dict) for item in page[key]):
            raise ProbeError()
        count += len(page[key])
        if key == "events" and count > 10_000:
            raise ProbeError()
        result.append(page)
        token = page.get("nextPageToken")
        if token is None or token == "":
            return result
        if not isinstance(token, str) or token in tokens:
            raise ProbeError()
        tokens.add(token)
    raise ProbeError()


def timezone(value: Any) -> str:
    try:
        if isinstance(value, str):
            ZoneInfo(value)
            return value
    except (ValueError, ZoneInfoNotFoundError):
        pass
    return "UTC"


def instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ProbeError()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProbeError()
    return parsed.astimezone(UTC)


def map_pages(listing: list[dict], start: datetime, end: datetime,
              source_timezone: str = "UTC") -> Snapshot:
    """Map already expanded provider instances to the existing snapshot contract."""
    events: dict[str, Event] = {}
    occurrences: list[Occurrence] = []
    ids: set[str] = set()
    try:
        for page in listing:
            if not isinstance(page.get("events"), list):
                raise ProbeError()
            for raw in page["events"]:
                if raw.get("status") == "cancelled":
                    continue
                oid = raw.get("id")
                eid = raw.get("recurringEventId") or oid
                title = raw.get("summary") or ""
                if (not isinstance(oid, str) or not oid or oid in ids
                        or not isinstance(eid, str) or not eid or not isinstance(title, str)):
                    raise ProbeError()
                ids.add(oid)
                begin, finish = raw["start"], raw["end"]
                if begin.get("date") is not None:
                    first, last = date.fromisoformat(begin["date"]), date.fromisoformat(finish["date"])
                    if last <= first:
                        last = first + timedelta(days=1)
                    row = Occurrence(oid, eid, title, start_date=first, end_date=last)
                    overlaps = first < end.date() and last > start.date()
                else:
                    row = normalize(Occurrence(
                        oid, eid, title, start_at=instant(begin["dateTime"]),
                        end_at=instant(finish["dateTime"]),
                        timezone=timezone(begin.get("timeZone") or page.get("timeZone") or source_timezone),
                    ))
                    overlaps = timed_overlaps(row.start_at, row.end_at, start, end)
                if overlaps:
                    occurrences.append(row)
                    events.setdefault(eid, Event(eid, title, {
                        "schema": "google-1", "recurring": bool(raw.get("recurringEventId")),
                    }))
        if len(ids) > 10_000:
            raise ProbeError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ProbeError() from None
    return Snapshot(list(events.values()), occurrences, complete=True)


def shape(listing: list[dict], key: str) -> dict:
    """Do not print data values, dynamic keys, IDs, tokens, or arbitrary string formats."""
    top: set[str] = set()
    event_keys: set[str] = set()
    formats: set[str] = set()
    unknown = 0
    for page in listing:
        top.update(TOP_KEYS.intersection(page))
        unknown += len(page.keys() - TOP_KEYS)
        if key == "events":
            for event in page[key]:
                event_keys.update(EVENT_KEYS.intersection(event))
                unknown += len(event.keys() - EVENT_KEYS)
                values = [event.get("created"), event.get("updated")]
                for field in ("start", "end", "originalStartTime"):
                    value = event.get(field)
                    if isinstance(value, dict):
                        values.extend((value.get("date"), value.get("dateTime")))
                for value in values:
                    if isinstance(value, str) and DATE_FORMAT.fullmatch(value):
                        formats.add(re.sub(r"\d", "#", value))
    return {"pages": len(listing), "count": sum(len(p[key]) for p in listing),
            "top_keys": sorted(top), "event_keys": sorted(event_keys),
            "unknown_key_count": unknown, "date_formats": sorted(formats)}


async def offline() -> dict:
    async def fixture_call(tool: str, arguments: dict) -> dict:
        name = "calendars" if tool == "list_calendars" else "events"
        suffix = "2" if arguments.get("pageToken") else "1"
        return json.loads((FIXTURES / f"{name}_{suffix}.json").read_text())

    calendars = await pages(fixture_call, "list_calendars", {"pageSize": 250})
    listing = await pages(fixture_call, "list_events", {"pageSize": 250})
    start, end = instant("2026-10-01T00:00:00Z"), instant("2026-11-01T00:00:00Z")
    snapshot = map_pages(listing, start, end)
    moved = map_pages([json.loads((FIXTURES / "events_moved.json").read_text())], start, end)
    try:
        map_pages([json.loads((FIXTURES / "malformed.json").read_text())], start, end)
    except ProbeError:
        malformed_rejected = True
    else:
        raise ProbeError()
    before = {row.external_id: row for row in snapshot.occurrences}
    after = {row.external_id: row for row in moved.occurrences}
    return {"mode": "offline", "calendars": shape(calendars, "calendars"),
            "events": shape(listing, "events"), "mapped_occurrences": len(before),
            "mapped_events": len(snapshot.events), "complete": snapshot.complete,
            "moved_identity_retained": any(before[k].start_at != after[k].start_at for k in before.keys() & after.keys()),
            "malformed_rejected": malformed_rejected,
            "writing": "blocked: calendar_write_capability_missing"}


async def live(arguments: argparse.Namespace) -> dict:
    calendars = await pages(live_call, "list_calendars", {"pageSize": 250})
    listing = await pages(live_call, "list_events", {
        "calendarId": arguments.calendar_id, "startTime": arguments.start.isoformat(),
        "endTime": arguments.end.isoformat(), "pageSize": arguments.page_size,
    })
    snapshot = map_pages(listing, arguments.start, arguments.end)
    return {"mode": "live", "calendars": shape(calendars, "calendars"),
            "events": shape(listing, "events"), "mapped_occurrences": len(snapshot.occurrences),
            "mapped_events": len(snapshot.events), "complete": snapshot.complete,
            "writing": "blocked: calendar_write_capability_missing"}


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse otherwise echoes user-supplied values (possibly private calendar IDs).
        super().error("invalid arguments; use --help for the required flags")


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--calendar-id")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--page-size", type=int, default=250)
    arguments = parser.parse_args(argv)
    if arguments.live:
        try:
            arguments.start, arguments.end = instant(arguments.start), instant(arguments.end)
            if not arguments.calendar_id or arguments.start >= arguments.end or not 1 <= arguments.page_size <= 250:
                raise ProbeError()
        except ValueError:
            parser.error("invalid live window")
    elif arguments.calendar_id or arguments.start or arguments.end or arguments.page_size != 250:
        parser.error("live options require --live")
    # httpx request URLs include private IDs; do not inherit verbose host logging in live mode.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(live(arguments) if arguments.live else offline())
    except Exception:
        print(json.dumps({"error": "provider_unavailable"}))
        return 1
    finally:
        logging.disable(previous_logging)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
