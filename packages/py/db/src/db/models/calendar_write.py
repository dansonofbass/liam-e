"""Durable write claims; terminal records retain no appointment text."""

from datetime import datetime

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from db.models._common import utc_datetime_column, utcnow


class CalendarWrite(SQLModel, table=True):
    __tablename__ = "calendar_write"
    __table_args__ = (
        Index("uq_calendar_write_running_target", "source_id", "target_external_id", unique=True,
              postgresql_where=text("status = 'running' AND target_external_id IS NOT NULL")),
    )

    id: str = Field(primary_key=True)
    source_id: str
    operation: str
    target_external_id: str | None = None
    request_json: str | None = None
    request_hash: str
    expected_revision: str | None = None
    status: str = "running"
    error_code: str | None = None
    result_external_id: str | None = None
    result_revision: str | None = None
    started_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column(nullable=False))
    finished_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
