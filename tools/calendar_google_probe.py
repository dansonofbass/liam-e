#!/usr/bin/env python3
"""Read-only Google Calendar capability probe; synthetic fixtures are the default.

Run with ``bash tools/uv.sh run --no-sync python tools/calendar_google_probe.py``.
Live access requires --live and an explicit calendar/window. Nothing is persisted.
Only structural statistics leave this process, even if a provider response is malformed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

from api.calendar.google import ProbeError, READ_TOOLS, instant, live_call, map_pages, pages

FIXTURES = Path(__file__).resolve().parents[1] / "apps/api/tests/fixtures/google_calendar"
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
