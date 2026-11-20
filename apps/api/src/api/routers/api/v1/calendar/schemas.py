"""Public calendar representations; connection references never leave the server."""

from datetime import date, datetime

from uuid import UUID

from db.accessors.calendar_source import ChatAccess

from pydantic import BaseModel, ConfigDict, Field


class SourceOut(BaseModel):
    id: str
    provider: str
    name: str
    timezone: str
    is_active: bool
    capabilities: list[str]
    chat_access: ChatAccess = "unreadable"
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
    editable: bool = False
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


class EventValuesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    start_local: str | None = None
    end_local: str | None = None
    timezone: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=8000)


class EventCreateIn(EventValuesIn):
    write_id: UUID
    source_id: str
    title: str = Field(min_length=1, max_length=500)


class EventUpdateIn(EventValuesIn):
    write_id: UUID
    expected_revision: str


class EventDeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    write_id: UUID
    expected_revision: str
