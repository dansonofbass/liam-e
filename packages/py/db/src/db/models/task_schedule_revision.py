"""A schedule revision and its persisted reconciliation progress."""

from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class TaskScheduleRevision(SQLModel, table=True):
    __tablename__ = 'task_schedule_revision'
    __table_args__ = (
        UniqueConstraint('series_id', 'version', name='uq_task_revision_series_version'),
        Index('ix_task_revision_series', 'series_id', 'version'),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    series_id: str
    version: int
    start_local: str
    timezone: str | None = None
    rrule: str | None = None
    end_key: str | None = None
    reconcile_target: str | None = None
    reconcile_cursor: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
