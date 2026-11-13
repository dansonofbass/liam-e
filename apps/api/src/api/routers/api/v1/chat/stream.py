"""Stream one agent turn as server-sent events."""
import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress

from db.accessors import chat_conversation
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, RootModel
from starlette.responses import JSONResponse, StreamingResponse
from mistralai_capabilities.fastapi.sse import event_stream_response, format_sse

from api.errors import refuse
from api.mail.agent import run_turn_events
from api.mail.chat_events import ChatEvent as ChatEventUnion, ErrorEvent

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatEvent(RootModel[ChatEventUnion]):
    """A discriminated event in the streamed response."""


class ChatStreamRequest(BaseModel):
    conversation_id: str | None = None
    text: str = Field(min_length=1, max_length=8000)
    account_id: str | None = None
    context_message_id: str | None = None


class EventStreamResponse(JSONResponse):
    media_type = 'text/event-stream'


async def sse_frames(events: AsyncIterator[ChatEventUnion], is_disconnected: Callable[[], Awaitable[bool]], *, ping_seconds: float = 15.0) -> AsyncIterator[str]:
    pending = None
    try:
        while True:
            if await is_disconnected():
                break
            if pending is None:
                pending = asyncio.ensure_future(anext(events))
            done, _ = await asyncio.wait({pending}, timeout=ping_seconds)
            if not done:
                yield ': ping\n\n'
                continue
            completed, pending = pending, None
            try:
                event = completed.result()
            except StopAsyncIteration:
                break
            yield format_sse(data=event.model_dump(mode='json'), event=event.event)
            if event.event in ('done', 'error'):
                break
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception as error:
        logger.warning('%s', type(error).__name__)
        yield format_sse(data=ErrorEvent(code='internal').model_dump(mode='json'), event='error')
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending
        await events.aclose()


@router.post('', operation_id='chat_stream', response_class=EventStreamResponse, response_model=ChatEvent, description='Streams one agent turn. It never sends mail itself; proposals require explicit confirmation.')
async def chat_stream(body: ChatStreamRequest, request: Request) -> StreamingResponse:
    if body.conversation_id is not None and await chat_conversation.get_conversation(body.conversation_id) is None:
        raise refuse(404, 'conversation_not_found', 'Diese Unterhaltung gibt es nicht mehr.')
    events = run_turn_events(**body.model_dump())
    return event_stream_response(sse_frames(events, request.is_disconnected))
