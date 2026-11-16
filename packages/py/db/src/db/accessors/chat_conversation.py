"""Accessor for ``chat_conversation`` rows."""

from sqlalchemy import select, update

from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.chat_conversation import ChatConversation


async def create_conversation(*, title: str = "", model: str = "") -> ChatConversation:
    async with get_session_maker()() as session:
        conversation = ChatConversation(title=title, model=model)
        session.add(conversation)
        await session.commit()
        return conversation


async def update_conversation(
    conversation_id: str, *, model: str | None = None, title: str | None = None
) -> ChatConversation | None:
    async with get_session_maker()() as session:
        conversation = await session.get(ChatConversation, conversation_id)
        if conversation is None:
            return None
        if model is not None:
            conversation.model = model
        if title is not None:
            conversation.title = title
        conversation.updated_at = utcnow()
        await session.commit()
        return conversation


async def get_conversation(conversation_id: str) -> ChatConversation | None:
    async with get_session_maker()() as session:
        return await session.get(ChatConversation, conversation_id)


async def list_conversations() -> list[ChatConversation]:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(ChatConversation).order_by(ChatConversation.updated_at.desc())
        )
        return list(result.scalars().all())


async def touch_conversation(
    conversation: ChatConversation, *, title: str | None = None
) -> ChatConversation:
    values = {"updated_at": utcnow()}
    if title:
        values["title"] = title
    async with get_session_maker()() as session:
        row = (await session.execute(update(ChatConversation).where(
            ChatConversation.id == conversation.id).values(**values).returning(ChatConversation))).scalar_one()
        await session.commit()
        return row
