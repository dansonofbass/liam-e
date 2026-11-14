"""Non-streaming compatibility endpoint for one chat turn."""
from db.accessors import chat_message as message_access
from fastapi import APIRouter
from pydantic import BaseModel, Field
from api.errors import refuse
from api.mail import agent
from . import schemas

router = APIRouter()


class ChatTurnRequest(BaseModel):
    conversation_id: str = Field(default='', description='Leer lassen für eine neue Unterhaltung')
    message: str


@router.post('', operation_id='chat_turn', summary='Send a message to the mail agent')
async def chat_turn(body: ChatTurnRequest) -> schemas.ChatTurnResponse:
    """Run a complete chat turn and return its visible messages."""
    conversation_id = ''
    user_id = ''
    try:
        async for event in agent.run_turn_events(conversation_id=body.conversation_id or None, text=body.message):
            if event.event == 'start':
                conversation_id, user_id = event.conversation_id, event.user_message_id
            elif event.event == 'error':
                if event.code == 'model_unavailable':
                    raise refuse(503, 'model_unavailable', 'Das Modell antwortet gerade nicht. Versuch es gleich noch mal.')
                raise refuse(500, 'internal', 'Die Antwort konnte nicht erstellt werden. Versuch es gleich noch mal.')
    except LookupError as error:
        raise refuse(404, 'conversation_not_found', 'Diese Unterhaltung gibt es nicht mehr. Starte eine neue Unterhaltung.') from error
    rows = await message_access.list_messages(conversation_id)
    index = next((i for i, row in enumerate(rows) if row.id == user_id), len(rows))
    return schemas.ChatTurnResponse(conversation_id=conversation_id, messages=[schemas.to_message_out(m) for m in agent.visible_messages(rows[index + 1:])])
