"""Read-only Studio Google Calendar connector, bounded snapshots and identity binding.

The primary listing's summary is the connector identity signal available in Studio.
It is hashed, never exposed as connection data, and checked before each snapshot.
Calendar tool permissions are deliberately separate from the mail allowlists.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from api.calendar.adapters import Event, Occurrence, Snapshot, normalize, timed_overlaps

READ_TOOLS = frozenset({"list_calendars", "list_events"})
Call = Callable[[str, dict[str, Any]], Awaitable[Any]]


class GoogleError(ValueError, LookupError):
    """Fixed public code only; LookupError prevents generic mail-worker retries."""

    def __init__(self, code: str = "provider_unavailable") -> None:
        self.code = code
        super().__init__(code)


# The probe's public exception name is retained for compatibility.
ProbeError = GoogleError


async def live_call(tool: str, arguments: dict[str, Any]) -> Any:
    """Reuse the connector REST transport, never the mail capability allowlists."""
    if tool not in READ_TOOLS:
        raise GoogleError()
    from api.mail.connectors import _call_tool

    try:
        return json.loads(await _call_tool("google_calendar", tool, arguments))
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        code = "provider_unavailable"
        if status in (401, 403) or (status == 404 and tool == "list_calendars"):
            code = "reconnect_required"
        elif status == 404:
            code = "calendar_unavailable"
        raise GoogleError(code) from None
    except Exception:
        raise GoogleError() from None


async def pages(call: Call, tool: str, arguments: dict[str, Any]) -> list[dict]:
    """Require every bounded page; filters remain identical when following a token."""
    if tool not in READ_TOOLS:
        raise GoogleError()
    key, cap = ("events", 40) if tool == "list_events" else ("calendars", 10)
    result: list[dict] = []
    tokens: set[str] = set()
    token = None
    count = 0
    for _ in range(cap):
        page = await call(tool, {**arguments, **({"pageToken": token} if token else {})})
        if not isinstance(page, dict) or not isinstance(page.get(key), list):
            raise GoogleError()
        if any(not isinstance(item, dict) for item in page[key]):
            raise GoogleError()
        count += len(page[key])
        if key == "events" and count > 10_000:
            raise GoogleError()
        result.append(page)
        token = page.get("nextPageToken")
        if token is None or token == "":
            return result
        if not isinstance(token, str) or token in tokens:
            raise GoogleError()
        tokens.add(token)
    raise GoogleError()


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
        raise GoogleError()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleError()
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
                raise GoogleError()
            for raw in page["events"]:
                if raw.get("status") == "cancelled":
                    continue
                oid = raw.get("id")
                eid = raw.get("recurringEventId") or oid
                title = raw.get("summary") or ""
                if (not isinstance(oid, str) or not oid or oid in ids
                        or not isinstance(eid, str) or not eid or not isinstance(title, str)):
                    raise GoogleError()
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
            raise GoogleError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise GoogleError() from None
    return Snapshot(list(events.values()), occurrences, complete=True)


async def identity(*, call: Call | None = None, now: datetime | None = None) -> str:
    """Read a tiny primary window without calendarId; never persist its summary."""
    now = now or datetime.now(UTC)
    page = await (call or live_call)("list_events", {
        "startTime": now.astimezone(UTC).isoformat(),
        "endTime": (now.astimezone(UTC) + timedelta(seconds=1)).isoformat(), "pageSize": 1,
    })
    if (not isinstance(page, dict) or not isinstance(page.get("summary"), str)
            or not page["summary"] or not isinstance(page.get("events"), list)):
        raise GoogleError()
    digest = hashlib.sha256(("google_calendar:" + page["summary"]).encode()).hexdigest()[:16]
    return f"google_calendar#{digest}"


@dataclass(frozen=True)
class GoogleSnapshot(Snapshot):
    source_revision: int


class GoogleConnectorAdapter:
    def __init__(self, *, call: Call | None = None, clock=None, jitter=None):
        self.call = call
        self.clock = clock or (lambda: datetime.now(UTC))
        self.jitter = jitter or random.uniform

    async def snapshot(self, source_id: str, start: datetime, end: datetime) -> GoogleSnapshot:
        from db.accessors import calendar_feed_sync, calendar_source, calendar_sync_state

        source = await calendar_source.get(source_id)
        if source is None or not source.is_active or source.provider != "google":
            raise GoogleError("calendar_unavailable")
        state = await calendar_sync_state.get(source_id)
        call = self.call or live_call
        try:
            if await identity(call=call, now=self.clock()) != source.connection_ref:
                raise GoogleError("reconnect_required")
            listing = await pages(call, "list_events", {
                "calendarId": source.external_id, "startTime": start.astimezone(UTC).isoformat(),
                "endTime": end.astimezone(UTC).isoformat(), "pageSize": 250,
            })
            snapshot = map_pages(listing, start, end, source.timezone)
            return GoogleSnapshot(snapshot.events, snapshot.occurrences, True, source.revision)
        except Exception as error:
            code = error.code if isinstance(error, GoogleError) else "provider_unavailable"
            failures = state.failure_count if state else 0
            await calendar_feed_sync.failure(
                source_id, revision=source.revision, now=self.clock(), code=code,
                delay_seconds=self.jitter(30, 60) * 2 ** min(failures, 2) if code == "provider_unavailable" else None,
            )
            raise GoogleError(code) from None
