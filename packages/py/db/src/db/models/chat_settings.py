"""Installation-wide grants for the chat. Account IDs survive credential renewal."""
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from db.models.prompt_template import OWNER_SCOPE


class ChatSettings(SQLModel, table=True):
    __tablename__ = "chat_settings"

    owner_scope: str = Field(default=OWNER_SCOPE, primary_key=True)
    account_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    version: int = 1
