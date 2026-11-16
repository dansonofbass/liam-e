"""One chat conversation with the mail agent."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class ChatConversation(SQLModel, table=True):
    __tablename__ = "chat_conversation"

    id: str = Field(default_factory=new_id, primary_key=True)
    title: str = ""
    model: str = ""
    prompt_revision_id: str | None = None
    version: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    account_scope_json: str | None = None
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
