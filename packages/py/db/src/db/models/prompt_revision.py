"""Immutable prompt revisions; deletion retains only content-free tombstones."""
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel
from db.models._common import new_id
from db.models.prompt_template import OWNER_SCOPE


class PromptRevision(SQLModel, table=True):
    __tablename__ = "prompt_revision"
    __table_args__ = (UniqueConstraint("template_id", "number"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE, index=True)
    template_id: str = Field(index=True)
    number: int
    content: str | None
    content_hash: str | None
    removed: bool = False
