"""List chat conversations."""

from db.accessors import chat_conversation as conversation_access
from fastapi import APIRouter
from pydantic import BaseModel, Field
from db.accessors import chat_context
from db.accessors.prompt_template import StaleVersion
from api.errors import refuse
from api.mail.models_catalog import list_chat_models, require_available_model

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
    expected_version: int = Field(ge=1)
    prompt_revision_id: str | None = None
    model: str | None = None
    title: str | None = None


@router.patch('/{conversation_id}', operation_id='chat_conversation_update', summary='Update a chat conversation')
async def update_conversation(conversation_id: str, body: ChatConversationUpdateIn) -> schemas.ConversationOut:
    """Change the title or the model used for future turns."""
    if await conversation_access.get_conversation(conversation_id) is None:
        raise refuse(404, 'conversation_not_found', 'Diese Unterhaltung gibt es nicht mehr. Starte eine neue Unterhaltung.')
    model = None
    title = None
    if 'model' in body.model_fields_set:
        model = body.model if body.model is not None else ''
        if body.model is not None:
            require_available_model(model, await list_chat_models())
    if 'title' in body.model_fields_set and body.title is not None:
        title = body.title.strip()[:120]
        if not title:
            raise refuse(422, 'title_empty', 'Gib einen Titel für die Unterhaltung ein.')
    try:
        conversation = await chat_context.configure(conversation_id, body.expected_version,
            model=model, title=title, revision_id=body.prompt_revision_id,
            change_revision='prompt_revision_id' in body.model_fields_set)
    except StaleVersion:
        raise refuse(409, 'version_conflict', 'Die Unterhaltung wurde inzwischen geändert. Lade sie neu.') from None
    except chat_context.ContextUnavailable:
        raise refuse(404, 'context_unavailable', 'Die Unterhaltung oder Vorlage ist nicht verfügbar. Lade die Übersicht neu.') from None
    if conversation is None:
        raise refuse(404, 'conversation_not_found', 'Diese Unterhaltung gibt es nicht mehr. Starte eine neue Unterhaltung.')
    return schemas.ConversationOut.from_model(conversation)
