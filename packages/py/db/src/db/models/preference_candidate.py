"""Unconfirmed preferences. Cards contain only IDs, never a second value copy."""
from datetime import datetime
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel
from db.models._common import new_id, utc_datetime_column, utcnow
from db.models.prompt_template import OWNER_SCOPE


class PreferenceCandidate(SQLModel, table=True):
    __tablename__ = 'preference_candidate'
    __table_args__ = (
        UniqueConstraint('owner_scope', 'source_message_id', 'key', 'scope'),
        CheckConstraint("key IN ('answer_length', 'salutation', 'signature')"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'expired')"),
        CheckConstraint("scope <> '' AND (key = 'answer_length' OR scope <> '*')"),
        CheckConstraint('value IS NULL OR length(value) BETWEEN 1 AND 500'),
        CheckConstraint("status NOT IN ('rejected', 'expired') OR value IS NULL"),
    )
    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE, index=True)
    conversation_id: str = Field(index=True)
    source_message_id: str = Field(index=True)
    key: str
    scope: str = '*'
    value: str | None = None
    status: str = 'pending'
    target_id: str | None = None
    expected_version: int = 0
    expected_revision_id: str | None = None
    proposal_id: str | None = Field(default=None, index=True)
    accepted_preference_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
