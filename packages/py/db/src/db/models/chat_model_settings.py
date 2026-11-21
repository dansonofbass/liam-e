"""The installation owner's configured default model for new conversations."""
from sqlmodel import Field, SQLModel

from db.models.prompt_template import OWNER_SCOPE


class ChatModelSettings(SQLModel, table=True):
    __tablename__ = "chat_model_settings"

    owner_scope: str = Field(default=OWNER_SCOPE, primary_key=True)
    # Keep the stored ID visible if the workspace removes it.
    default_model: str | None = None
    version: int = 1
