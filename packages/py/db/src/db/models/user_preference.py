"""Explicit, bounded preferences; removed rows are content-free suppression references."""
from datetime import datetime
from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field, SQLModel
from db.models._common import new_id, utc_datetime_column
from db.models.prompt_template import OWNER_SCOPE

GLOBAL_SCOPE = '*'


class UserPreference(SQLModel, table=True):
    __tablename__ = 'user_preference'
    __table_args__ = (
        CheckConstraint("key IN ('answer_length', 'salutation', 'signature')"),
        CheckConstraint("status IN ('active', 'paused', 'removed')"),
        CheckConstraint("scope <> '' AND (key = 'answer_length' OR scope <> '*')"),
        Index('uq_preference_active_scope', 'owner_scope', 'key', 'scope', unique=True,
              postgresql_where=text("status = 'active'")),
    )
    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE, index=True)
    key: str
    scope: str = GLOBAL_SCOPE
    status: str = 'active'
    revision_id: str | None = None
    version: int = 1
    removed_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
