"""Persistent calendar coverage and last successful refresh."""

from datetime import datetime

from sqlalchemy import Column, Integer, Text, text
from sqlmodel import Field, SQLModel

from db.models._common import utc_datetime_column


class CalendarSyncState(SQLModel, table=True):
    __tablename__ = "calendar_sync_state"

    source_id: str = Field(primary_key=True)
    coverage_start: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    coverage_end: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_success_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    incomplete: bool = True
    last_checked_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_validated_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    next_attempt_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_error: str | None = None
    failure_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    data_revision: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    encrypted_validators: str | None = Field(default=None, repr=False, sa_column=Column(Text, nullable=True))
