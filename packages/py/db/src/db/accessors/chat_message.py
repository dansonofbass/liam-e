"""Accessor for ``chat_message`` rows: append-only chat history plus draft bookkeeping."""

from sqlalchemy import select

from db.engine import get_session_maker
from db.models.chat_message import ChatMessage


async def add_message(
    *,
    conversation_id: str,
    role: str,
    content: str = "",
    tool_name: str = "",
    tool_payload_json: str = "",
    draft_json: str = "",
) -> ChatMessage:
    async with get_session_maker()() as session:
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_payload_json=tool_payload_json,
            draft_json=draft_json,
        )
        session.add(message)
        await session.commit()
        return message


async def get_message(message_id: str) -> ChatMessage | None:
    async with get_session_maker()() as session:
        return await session.get(ChatMessage, message_id)


async def list_messages(conversation_id: str) -> list[ChatMessage]:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at)
        )
        return list(result.scalars().all())


async def update_draft_json(message_id: str, draft_json: str) -> ChatMessage | None:
    async with get_session_maker()() as session:
        message = await session.get(ChatMessage, message_id)
        if message is None:
            return None
        message.draft_json = draft_json
        session.add(message)
        await session.commit()
        return message
