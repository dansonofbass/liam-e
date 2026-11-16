"""Revocable, content-free turn provenance, including a preference revision extension point."""
from sqlmodel import Field, SQLModel
from db.models._common import new_id


class ChatContext(SQLModel, table=True):
    __tablename__ = "chat_context"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(index=True)
    prompt_revision_id: str | None = Field(default=None, index=True)
    prompt_hash: str | None = None
    app_prompt_version: str
    account_scope_json: str
    preference_revision_id: str | None = None
    revoked: bool = False
