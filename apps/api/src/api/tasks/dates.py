"""Local task boundaries; legacy date-only schedules use UTC without rewriting data."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def is_future(due_local: str, zone: str | None, now: datetime) -> bool:
    """Today's date is already due; date-only overdue starts on the next local day."""
    if now.tzinfo is None:
        raise ValueError('current time must be timezone-aware')
    local_now = now.astimezone(ZoneInfo(zone or 'UTC'))
    if 'T' in due_local.upper():
        return datetime.fromisoformat(due_local).replace(tzinfo=local_now.tzinfo, fold=0).astimezone(UTC) > now.astimezone(UTC)
    return date.fromisoformat(due_local) > local_now.date()


def is_overdue(due_local: str, zone: str | None, now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError('current time must be timezone-aware')
    local_now = now.astimezone(ZoneInfo(zone or 'UTC'))
    if 'T' in due_local.upper():
        return datetime.fromisoformat(due_local).replace(tzinfo=local_now.tzinfo, fold=0).astimezone(UTC) < now.astimezone(UTC)
    return date.fromisoformat(due_local) < local_now.date()
