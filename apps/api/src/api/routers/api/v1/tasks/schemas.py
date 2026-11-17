"""Request and response shapes for personal tasks."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    creation_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default='', max_length=10000)
    start: str = Field(min_length=10, max_length=26)
    timezone: str | None = Field(default=None, max_length=100, description='Required IANA timezone, including for date-only tasks; missing or invalid values return task_invalid.')
    rrule: str | None = Field(default=None, max_length=500)
    source_account_id: str | None = Field(default=None, max_length=200)
    source_message_id: str | None = Field(default=None, max_length=200)


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: str = Field(min_length=10, max_length=26)
    through: str = Field(min_length=10, max_length=26)
    timezone: str = Field(min_length=1, max_length=100)
    rrule: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=100, ge=1, le=100)


class PreviewException(BaseModel):
    local: str
    reason: Literal['invalid_date', 'nonexistent_time']
    monthday: int | None


class PreviewOut(BaseModel):
    occurrences: list[str]
    exceptions: list[PreviewException]
    through: str
    complete: bool


class ReconcileIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    series_id: str = Field(min_length=1, max_length=200)
    revision_id: str | None = Field(default=None, max_length=200)
    cursor: str | None = Field(default=None, max_length=1024)
    advance: bool = False
    limit: int = Field(default=100, ge=1, le=100)


class ReconcileOut(BaseModel):
    revision_id: str
    cursor: str
    target: datetime
    complete: bool


class TaskCreated(BaseModel):
    id: str
    version: int
    created: bool


class VersionIn(BaseModel):
    version: int = Field(ge=1)


class OccurrenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    series_id: str
    revision_id: str
    occurrence_key: str
    due_local: str
    due_at: datetime | None
    status: Literal['open', 'completed', 'skipped', 'cancelled']
    version: int


class OccurrencePage(BaseModel):
    items: list[OccurrenceOut]
    next_cursor: str | None
