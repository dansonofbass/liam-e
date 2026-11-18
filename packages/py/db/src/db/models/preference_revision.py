"""Immutable manual confirmations, except irreversible content removal."""
from datetime import datetime
from sqlalchemy import CheckConstraint, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel
from db.models._common import new_id, utcnow
from db.models.prompt_template import OWNER_SCOPE


class PreferenceRevision(SQLModel, table=True):
    __tablename__ = 'preference_revision'
    __table_args__ = (
        UniqueConstraint('preference_id', 'number'),
        CheckConstraint('value IS NULL OR (length(value) BETWEEN 1 AND 500)'),
    )
    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE, index=True)
    preference_id: str = Field(index=True)
    number: int
    key: str
    scope: str
    value: str | None
    source: str = 'manual'
    confirmed_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    removed: bool = False
