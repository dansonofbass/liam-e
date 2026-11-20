"""Versioned skill definitions within the single-owner installation scope.

Deployment access is restricted externally to one owner. ``OWNER_SCOPE`` is an
installation-wide server constant and is never derived from request data.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column
from db.models.prompt_template import OWNER_SCOPE


class SkillDefinition(SQLModel, table=True):
    __tablename__ = "skill_definition"
    __table_args__ = (
        UniqueConstraint("owner_scope", "slug", name="uq_skill_definition_owner_slug"),
        CheckConstraint("origin IN ('builtin', 'custom')", name="ck_skill_definition_origin"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_skill_definition_status"),
        Index("ix_skill_definition_owner_status", "owner_scope", "status"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE, index=True)
    slug: str
    origin: str = "custom"
    status: str = "active"
    name: str
    description: str
    version: int = 1
    revision_id: str
    updated_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
