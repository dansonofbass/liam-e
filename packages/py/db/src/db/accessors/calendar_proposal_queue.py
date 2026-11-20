"""Keep prepared appointments behind the conversation's single confirmation card."""

import json
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from db.accessors import calendar_source, chat_settings
from db.engine import get_session_maker
from db.models.chat_context import ChatContext
from db.models.chat_message import ChatMessage


class SequenceReplaced(ValueError):
    """Another proposal superseded this appointment sequence."""


def sequence_extras(followups: Sequence[dict] = ()) -> str:
    return json.dumps({"calendar_followups": list(followups)})


async def _publish_next(session: AsyncSession, previous: ChatMessage, extras: dict) -> ChatMessage | None:
    following, *remaining = extras.pop("calendar_followups")
    payload = following["proposal"]
    context = await session.get(ChatContext, following["context_id"])
    if (context is None or context.revoked or context.conversation_id != previous.conversation_id
            or not await chat_settings.permits_context(session, context)
            or not await calendar_source.permits_context(session, context)):
        return None
    card = ChatMessage(conversation_id=previous.conversation_id, context_id=context.id,
        role="proposal", proposal_status="pending", content=payload["reason"], proposal_json=json.dumps(payload),
        extras_json=sequence_extras(remaining))
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
    extras = json.loads(card.extras_json)
    if "calendar_followups" not in extras or extras.get("calendar_sequence_closed"):
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
            extras = json.loads(card.extras_json or "{}")
            card_id = extras.get("next_calendar_proposal_id")
            if not card_id:
                break
        closed = extras.get("calendar_sequence_closed")
        if "calendar_followups" not in extras or (not closed and card.proposal_status not in {"pending", "running", "unknown"}):
            raise SequenceReplaced
        extras["calendar_followups"].append({"context_id": context_id, "proposal": payload})
        published = None
        if closed:
            published = await _publish_next(session, card, extras)
            if published is None:
                raise SequenceReplaced
        card.extras_json = json.dumps(extras)
        return published
