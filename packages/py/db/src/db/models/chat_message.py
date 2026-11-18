"""One message in a chat conversation.

``role`` is ``user``, ``assistant``, ``tool`` or ``proposal``; legacy rows may use
``draft`` and ``draft_json``. Assistant messages that called tools carry their calls in
``tool_payload_json``. Proposals are stored in ``proposal_json`` with ``proposal_status``;
their actions are executed only after ``POST /api/v1/chat/proposals/{proposal_id}/confirm``.
"""

from datetime import datetime

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_message"
    __table_args__ = (
        Index("ix_chat_message_conversation_created", "conversation_id", "created_at"),
        Index("uq_chat_message_open_proposal", "conversation_id", unique=True,
              postgresql_where=text("proposal_status = 'pending'")),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(index=True)
    role: str
    context_id: str | None = None
    content: str = ""
    tool_name: str = ""
    tool_payload_json: str = ""
    draft_json: str = ""
    proposal_json: str = ""
    proposal_status: str = ""  # pending, running, done, partial, failed, unknown or cancelled
    stopped: bool = False
    extras_json: str = ""  # mails, suggestions and model
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
