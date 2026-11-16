"""A materialized task occurrence, keyed by its original local schedule value."""

from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class TaskOccurrence(SQLModel, table=True):
    __tablename__ = 'task_occurrence'
    __table_args__ = (
        UniqueConstraint('revision_id', 'occurrence_key', name='uq_task_occurrence_revision_key'),
        Index('ix_task_occurrence_series_due', 'series_id', 'due_local', 'id'),
        Index('ix_task_occurrence_status_due', 'status', 'due_local', 'id'),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    series_id: str
    revision_id: str
    occurrence_key: str
    due_local: str
    due_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    status: str = 'open'
    version: int = 1
    created_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
