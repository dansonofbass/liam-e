"""One chat turn: persists the user message, runs the agent tool loop, returns the new messages."""

from db.accessors import chat_conversation as conversation_access
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.mail import agent

from . import schemas

router = APIRouter()


class ChatTurnRequest(BaseModel):
    conversation_id: str = Field(
        default="", description="Leer lassen für eine neue Konversation"
    )
    message: str


@router.post("", operation_id="chat_turn", summary="Send a message to the mail agent")
async def chat_turn(body: ChatTurnRequest) -> schemas.ChatTurnResponse:
    """Send one chat message to the mail agent and return the messages it produced.

    Pass an empty ``conversation_id`` to start a new conversation; the response returns the
    conversation id to continue with. The agent may create a pending draft, but this operation
    never sends a mail by itself.
    """
    if body.conversation_id:
        conversation = await conversation_access.get_conversation(body.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Konversation nicht gefunden.")
    else:
        conversation = await conversation_access.create_conversation()
    try:
        _, new_messages = await agent.run_turn(conversation.id, body.message)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return schemas.ChatTurnResponse(
        conversation_id=conversation.id,
        messages=[schemas.to_message_out(m) for m in new_messages],
    )
