"""List chat conversations."""

from db.accessors import chat_conversation as conversation_access
from fastapi import APIRouter
from pydantic import BaseModel
from api.errors import refuse
from api.mail.models_catalog import list_chat_models

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


class ChatConversationUpdateIn(BaseModel):
    model: str | None = None
    title: str | None = None


@router.patch('/{conversation_id}', operation_id='chat_conversation_update', summary='Update a chat conversation')
async def update_conversation(conversation_id: str, body: ChatConversationUpdateIn) -> schemas.ConversationOut:
    """Change the title or the model used for future turns."""
    if await conversation_access.get_conversation(conversation_id) is None:
        raise refuse(404, 'conversation_not_found', 'Diese Unterhaltung gibt es nicht mehr.')
    model = None
    title = None
    if 'model' in body.model_fields_set:
        model = body.model if body.model is not None else ''
        if body.model is not None and model not in {m.id for m in await list_chat_models()}:
            raise refuse(422, 'model_unknown', 'Dieses Modell ist nicht verfügbar. Wähle ein anderes Modell.')
    if 'title' in body.model_fields_set and body.title is not None:
        title = body.title.strip()[:120]
        if not title:
            raise refuse(422, 'title_empty', 'Gib einen Titel für die Unterhaltung ein.')
    conversation = await conversation_access.update_conversation(conversation_id, model=model, title=title)
    if conversation is None:
        raise refuse(404, 'conversation_not_found', 'Diese Unterhaltung gibt es nicht mehr.')
    return schemas.ConversationOut.from_model(conversation)
