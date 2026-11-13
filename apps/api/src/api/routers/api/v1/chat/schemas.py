"""Shared response models for the chat routers. Private module: not a route."""

from datetime import datetime

from db.models.chat_conversation import ChatConversation
from api.mail.chat_schemas import ChatExtrasOut, ChatMessageOut, to_message_out  # noqa: F401
from pydantic import BaseModel


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, conversation: ChatConversation) -> "ConversationOut":
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class ChatTurnResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessageOut]
