"""Calendar instances with stable provider identity and half-open intervals."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column


class CalendarOccurrence(SQLModel, table=True):
    __tablename__ = "calendar_occurrence"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_calendar_occurrence_external"),
        CheckConstraint("(start_date IS NOT NULL AND end_date IS NOT NULL AND start_date < end_date AND start_at IS NULL AND end_at IS NULL AND timezone IS NULL) OR (start_date IS NULL AND end_date IS NULL AND start_at IS NOT NULL AND end_at IS NOT NULL AND start_at <= end_at AND timezone IS NOT NULL)", name="ck_calendar_occurrence_interval"),
        Index("ix_calendar_occurrence_dates", "source_id", "start_date", "end_date"),
        Index("ix_calendar_occurrence_times", "source_id", "start_at", "end_at"),
        # Unfiltered window reads: an occurrence overlaps a window only if it ends after the window
        # starts, so these keep past rows out of the scan as the index grows.
        Index("ix_calendar_occurrence_end_at", "end_at"),
        Index("ix_calendar_occurrence_end_date", "end_date"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    source_id: str
    event_id: str
    external_id: str
    title: str = ""
    start_date: date | None = None
    end_date: date | None = None
    start_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    end_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    timezone: str | None = None
