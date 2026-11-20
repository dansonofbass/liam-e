"""Keep prepared appointments behind the conversation's single confirmation card."""

import json
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from db.accessors import calendar_source, chat_settings
from db.engine import get_session_maker
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState
from db.models.chat_context import ChatContext
from db.models.chat_message import ChatMessage


class SequenceReplaced(ValueError):
    """Another proposal superseded this appointment sequence."""


class TargetUnavailable(ValueError):
    """The prepared calendar no longer permits this proposal."""


async def can_offer(session: AsyncSession, conversation_id: str, context_id: str | None,
                    source_id: str, connection_ref: str) -> bool:
    if not context_id:
        return False
    context = await session.get(ChatContext, context_id, with_for_update={"read": True}, populate_existing=True)
    if (context is None or context.revoked or context.conversation_id != conversation_id
            or source_id not in json.loads(context.calendar_scope_json)):
        return False
    # Sync and source lifecycle writers lock this row before changing capabilities
    # or sync state. Keep a shared lock until the card or queue entry commits.
    source = await session.get(CalendarSource, source_id, with_for_update={"read": True}, populate_existing=True)
    if source is None or source.connection_ref != connection_ref:
        return False
    state = await session.get(CalendarSyncState, source_id, populate_existing=True)
    return (calendar_source.chat_access(source, state) == "writable"
            and await chat_settings.permits_context(session, context)
            and await calendar_source.permits_context(session, context))


def sequence_extras(followups: Sequence[dict] = ()) -> str:
    return json.dumps({"calendar_followups": list(followups)})


def _metadata(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def _publish_next(session: AsyncSession, previous: ChatMessage, extras: dict) -> ChatMessage | None:
    followups = extras.pop("calendar_followups")
    for position, following in enumerate(followups):
        try:
            payload = following["proposal"]
            context_id = following["context_id"]
            target = payload["calendar"]
            source_id, connection = target["source_id"], target["connection_ref"]
            if (payload["kind"] != "calendar" or target["action"] != "create" or not isinstance(payload["reason"], str)
                    or not all(isinstance(value, str) and value for value in (context_id, source_id, connection))):
                continue
        except (KeyError, TypeError):
            # An unreadable queued entry cannot hold up settlement of the
            # preceding card or a later appointment with a verifiable target.
            continue
        if await can_offer(session, previous.conversation_id, context_id, source_id, connection):
            break
    else:
        # All prepared targets expired. A still-unfinished appointment can later
        # use the empty sequence, as it could after settling a card with no queue.
        extras["calendar_followups"] = []
        return None
    card = ChatMessage(conversation_id=previous.conversation_id, context_id=context_id,
        role="proposal", proposal_status="pending", content=payload["reason"], proposal_json=json.dumps(payload),
        extras_json=sequence_extras(followups[position + 1:]))
    # A new request can take the conversation's pending slot while Google finishes
    # the first write. Its card takes precedence without rolling back that outcome.
    statement = insert(ChatMessage).values(**card.model_dump()).on_conflict_do_nothing(
        index_elements=[ChatMessage.conversation_id], index_where=text("proposal_status = 'pending'")).returning(ChatMessage)
    published = (await session.execute(statement)).scalar_one_or_none()
    if published:
        extras["next_calendar_proposal_id"] = published.id
    return published


async def release(session: AsyncSession, card: ChatMessage | None) -> None:
    """Advance only on an explicit cancellation or a settled confirmation, in its transaction."""
    if card is None or not card.extras_json or card.proposal_status not in {"cancelled", "done", "failed"}:
        return
    extras = _metadata(card.extras_json)
    if not isinstance(extras.get("calendar_followups"), list) or extras.get("calendar_sequence_closed"):
        return
    extras["calendar_sequence_closed"] = True
    if extras["calendar_followups"]:
        await _publish_next(session, card, extras)
    card.extras_json = json.dumps(extras)


async def append(first_id: str, *, conversation_id: str, context_id: str | None, payload: dict) -> ChatMessage | None:
    """An owner in another tab may already have advanced the sequence by one or more cards."""
    async with get_session_maker().begin() as session:
        card_id = first_id
        while True:
            card = await session.get(ChatMessage, card_id, with_for_update=True)
            if card is None or card.conversation_id != conversation_id:
                raise SequenceReplaced
            extras = _metadata(card.extras_json)
            card_id = extras.get("next_calendar_proposal_id")
            if not card_id:
                break
            if not isinstance(card_id, str):
                raise SequenceReplaced
        closed = extras.get("calendar_sequence_closed")
        if not isinstance(extras.get("calendar_followups"), list) or (not closed and card.proposal_status not in {"pending", "running", "unknown"}):
            raise SequenceReplaced
        target = payload["calendar"]
        if not await can_offer(session, conversation_id, context_id, target["source_id"], target["connection_ref"]):
            raise TargetUnavailable
        extras["calendar_followups"].append({"context_id": context_id, "proposal": payload})
        published = None
        if closed:
            published = await _publish_next(session, card, extras)
            if published is None:
                raise SequenceReplaced
        card.extras_json = json.dumps(extras)
        return published
