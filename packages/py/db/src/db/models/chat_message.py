"""One message in a chat conversation.

``role`` is ``user``, ``assistant``, ``tool`` or ``draft``. Assistant messages that called tools
carry their tool calls in ``tool_payload_json``; ``draft`` messages carry the pending send in
``draft_json`` (``{"status": "pending" | "sent" | "cancelled", ...}``) — a draft is only sent after
the explicit confirm endpoint runs.
"""

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_message"
    __table_args__ = (
        Index("ix_chat_message_conversation_created", "conversation_id", "created_at"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(index=True)
    role: str
    content: str = ""
    tool_name: str = ""
    tool_payload_json: str = ""
    draft_json: str = ""
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
