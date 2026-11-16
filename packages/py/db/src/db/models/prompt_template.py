"""Single-owner prompt metadata; deployment access control is assumed, not verified here.

The owner is an installation-wide server constant, never a request identity.
"""
from sqlmodel import Field, SQLModel
from db.models._common import new_id

OWNER_SCOPE = "installation"


class PromptTemplate(SQLModel, table=True):
    __tablename__ = "prompt_template"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE, index=True)
    name: str
    version: int = 1
    revision_id: str
