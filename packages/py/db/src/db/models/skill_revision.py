"""Immutable skill revisions; deletion retains only content-free tombstones."""

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id
from db.models.prompt_template import OWNER_SCOPE


class SkillRevision(SQLModel, table=True):
    __tablename__ = "skill_revision"
    __table_args__ = (UniqueConstraint("skill_id", "number", name="uq_skill_revision_skill_number"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE, index=True)
    skill_id: str = Field(index=True)
    number: int
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    workflow_steps_json: str | None = None
    allowed_tools_json: str | None = None
    content_hash: str | None = None
    removed: bool = False
