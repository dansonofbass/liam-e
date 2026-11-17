"""Persistent calendar coverage and last successful refresh."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from db.models._common import utc_datetime_column


class CalendarSyncState(SQLModel, table=True):
    __tablename__ = "calendar_sync_state"

    source_id: str = Field(primary_key=True)
    coverage_start: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    coverage_end: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_success_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    incomplete: bool = True
