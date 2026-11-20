"""Revocable, content-free turn provenance, including a preference revision extension point."""
from sqlmodel import Field, SQLModel
from sqlalchemy import Boolean, Column, Text
from db.models._common import new_id


class ChatContext(SQLModel, table=True):
    __tablename__ = "chat_context"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(index=True)
    prompt_revision_id: str | None = Field(default=None, index=True)
    prompt_hash: str | None = None
    app_prompt_version: str
    mail_scope_version: int | None = None
    account_scope_json: str
    calendar_scope_json: str = Field(default="[]", sa_column=Column(Text, nullable=False, server_default="[]"))
    calendar_feed_bindings_json: str = Field(default="{}", repr=False, sa_column=Column(Text, nullable=False, server_default="{}"))
    task_scope_json: str = Field(default='{"source":"none"}', sa_column=Column(Text, nullable=False, server_default='{"source":"none"}'))
    preference_revision_id: str | None = None
    preference_revision_ids_json: str = Field(default='[]', sa_column=Column(Text, nullable=False, server_default='[]'))
    preference_resolver_version: str = Field(default='1', sa_column=Column(Text, nullable=False, server_default='1'))
    preferences_enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default='false'))
    skill_id: str | None = Field(default=None, index=True)
    skill_revision_id: str | None = Field(default=None, index=True)
    skill_hash: str | None = None
    revoked: bool = False
