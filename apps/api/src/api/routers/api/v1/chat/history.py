"""The message history of one conversation."""

from typing import Annotated

from db.accessors import chat_conversation as conversation_access
from db.accessors import chat_message as message_access
from fastapi import APIRouter, Query

from api.errors import refuse

from api.mail.agent import visible_messages

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
    """Return every message of one conversation in conversation order.

    ``conversation_id`` selects the conversation; an unknown id answers 404.
    """
    conversation = await conversation_access.get_conversation(conversation_id)
    if conversation is None:
        raise refuse(404, "conversation_not_found", "Diese Unterhaltung gibt es nicht mehr. Starte eine neue Unterhaltung.")
    messages = await message_access.list_messages(conversation_id)
    return [schemas.to_message_out(m) for m in visible_messages(messages)]
