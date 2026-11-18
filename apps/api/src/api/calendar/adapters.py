"""Snapshot contract shared by expanded and recurrence-aware providers.

Adapters must return the complete requested window, including an explicit completeness flag.
Network access and recurrence expansion belong to provider implementations, not this contract.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Event:
    external_id: str
    title: str = ""
    recurrence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Occurrence:
    external_id: str
    event_external_id: str
    title: str = ""
    start_date: date | None = None
    end_date: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = None
    editable: bool = False


@dataclass(frozen=True)
class Snapshot:
    events: list[Event]
    occurrences: list[Occurrence]
    complete: bool


class Adapter(Protocol):
    async def snapshot(self, source_id: str, start: datetime, end: datetime) -> Snapshot: ...


def timed_overlaps(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> bool:
    """Match half-open intervals and points in [window_start, window_end)."""
    return start < window_end and end >= window_start and (end > window_start or start == end)


def normalize(row: Occurrence) -> Occurrence:
    """Validate one all-day interval or timed interval/point and normalize instants to UTC."""
    if row.start_date is not None or row.end_date is not None:
        if (type(row.start_date) is not date or type(row.end_date) is not date
                or row.start_date >= row.end_date or row.start_at is not None
                or row.end_at is not None or row.timezone is not None):
            raise ValueError("invalid all-day interval")
        return row
    if row.start_at is None or row.end_at is None or row.timezone is None:
        raise ValueError("invalid timed interval")
    zone = ZoneInfo(row.timezone)
    for instant in (row.start_at, row.end_at):
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("naive instant")
        local = instant.astimezone(UTC).astimezone(zone)
        if getattr(instant.tzinfo, "key", None) == row.timezone and local.replace(tzinfo=None) != instant.replace(tzinfo=None):
            raise ValueError("nonexistent local time")
    start, end = row.start_at.astimezone(UTC), row.end_at.astimezone(UTC)
    if start > end:
        raise ValueError("invalid timed interval")
    return Occurrence(external_id=row.external_id, event_external_id=row.event_external_id,
                      title=row.title, start_at=start, end_at=end, timezone=row.timezone, editable=row.editable)
