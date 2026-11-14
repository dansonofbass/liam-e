"""Chat response models shared by the domain and HTTP routes."""

import json
from datetime import datetime

from db.models.chat_message import ChatMessage
from pydantic import BaseModel, Field

from api.mail.proposals import Proposal, proposal_view


class ChatExtrasOut(BaseModel):
    mails: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    model: str = ""


class ChatMessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    tool_name: str
    created_at: datetime
    proposal: Proposal | None
    proposal_status: str
    stopped: bool
    extras: ChatExtrasOut


def to_message_out(message: ChatMessage) -> ChatMessageOut:
    status = ""
    if message.role == "proposal":
        status = message.proposal_status
    elif message.role == "draft":
        status = {"sent": "done", "failed": "failed", "cancelled": "cancelled", "pending": "cancelled"}.get(json.loads(message.draft_json).get("status"), "cancelled")
    return ChatMessageOut(
        id=message.id, conversation_id=message.conversation_id, role=message.role,
        content=message.content, tool_name=message.tool_name, created_at=message.created_at,
        proposal=proposal_view(message), proposal_status=status, stopped=message.stopped,
        extras=ChatExtrasOut.model_validate_json(message.extras_json) if message.extras_json else ChatExtrasOut(),
    )
