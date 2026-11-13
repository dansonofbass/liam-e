"""List chat conversations."""

from db.accessors import chat_conversation as conversation_access
from fastapi import APIRouter

from . import schemas

router = APIRouter()


@router.get(
    "",
    operation_id="chat_conversations_list",
    summary="List all chat conversations, newest first",
)
async def list_conversations() -> list[schemas.ConversationOut]:
    """List all chat conversations, most recently updated first."""
    conversations = await conversation_access.list_conversations()
    return [schemas.ConversationOut.from_model(c) for c in conversations]
