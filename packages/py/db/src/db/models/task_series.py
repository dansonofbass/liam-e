"""A personal task series and its idempotent creation identity."""

from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class TaskSeries(SQLModel, table=True):
    __tablename__ = 'task_series'
    __table_args__ = (
        UniqueConstraint('scope', 'creation_key', name='uq_task_series_scope_creation_key'),
        Index('ix_task_series_scope_source', 'scope', 'source_account_id', 'source_message_id'),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    scope: str
    creation_key: str
    creation_hash: str
    title: str
    description: str = ''
    source_account_id: str | None = None
    source_message_id: str | None = None
    version: int = 1
    archived: bool = False
    created_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
