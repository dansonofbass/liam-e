"""Shared response models for the chat routers. Private module: not a route."""

from datetime import datetime

from db.models.chat_conversation import ChatConversation
from db.models.chat_message import ChatMessage
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


class ChatMessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    tool_name: str
    draft_json: str
    created_at: datetime

    @classmethod
    def from_model(cls, message: ChatMessage) -> "ChatMessageOut":
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            tool_name=message.tool_name,
            draft_json=message.draft_json,
            created_at=message.created_at,
        )


class ChatTurnResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessageOut]
