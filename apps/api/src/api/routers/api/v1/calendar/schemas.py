"""Public calendar representations; connection references never leave the server."""

from datetime import date, datetime

from pydantic import BaseModel


class SourceOut(BaseModel):
    id: str
    provider: str
    name: str
    timezone: str
    is_active: bool
    capabilities: list[str]
    coverage_start: datetime | None
    coverage_end: datetime | None
    last_success_at: datetime | None
    stale: bool
    incomplete: bool
    revision: int = 1
    last_checked_at: datetime | None = None
    last_validated_at: datetime | None = None
    last_error: str | None = None
    data_revision: int = 0


class SourcePatch(BaseModel):
    is_active: bool


class OccurrenceOut(BaseModel):
    id: str
    source_id: str
    event_id: str
    title: str
    start_date: date | None
    end_date: date | None
    start_at: datetime | None
    end_at: datetime | None
    timezone: str | None


class OccurrencePage(BaseModel):
    items: list[OccurrenceOut]
    next_cursor: str | None


class SyncOut(BaseModel):
    queued: bool
