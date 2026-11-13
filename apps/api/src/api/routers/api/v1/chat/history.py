"""The message history of one conversation."""

from typing import Annotated

from db.accessors import chat_conversation as conversation_access
from db.accessors import chat_message as message_access
from fastapi import APIRouter, HTTPException, Query

from . import schemas

router = APIRouter()


@router.get(
    "",
    operation_id="chat_history",
    summary="All messages of one conversation, in order",
)
async def history(
    conversation_id: Annotated[str, Query()],
) -> list[schemas.ChatMessageOut]:
    conversation = await conversation_access.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden.")
    messages = await message_access.list_messages(conversation_id)
    return [schemas.ChatMessageOut.from_model(m) for m in messages]
