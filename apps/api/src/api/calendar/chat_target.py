"""Server-owned target of one appointment awaiting clarification."""

import json
import re
from typing import Literal

from db.accessors import calendar_source
from pydantic import BaseModel


class CalendarChoice(BaseModel):
    name: str
    source_id: str | None = None
    connection_ref: str | None = None
    error: Literal["calendar_name_ambiguous", "calendar_name_unknown"] | None = None


def mentions(text: str, name: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", text.casefold()))


def _new_appointment(text: str) -> bool:
    explicit = r"\b(?:another|different|new|weiteren?|andere[nmrs]?|neue[nmrs]?)\s+(?:appointment|event|meeting|termin)\b"
    fresh = r"\b(?:create|schedule|book|arrange|add|erstelle|plane)\s+(?:a|an|another|einen?|eine[nmrs]?)\s"
    return bool(re.search(explicit, text, re.I) or re.search(fresh, text, re.I))


def previous_choice(history, user_id: str, text: str, contexts) -> CalendarChoice | None:
    if len(history) < 2 or history[-1].id != user_id:
        return None
    reply = history[-2]
    if reply.role != "assistant" or reply.tool_payload_json or reply.stopped or not reply.extras_json:
        return None
    previous_user = next((row for row in reversed(history[:-2]) if row.role == "user"), None)
    context = contexts.get(reply.context_id)
    if not previous_user or previous_user.context_id != reply.context_id or not context or context.revoked:
        return None
    try:
        data = json.loads(reply.extras_json).get("calendar_clarification")
        return CalendarChoice.model_validate(data) if data and not _new_appointment(text) else None
    except (AttributeError, TypeError, ValueError):
        return None


def named_choice(name, entries):
    matches = [source for source, state in entries if source.name.strip().casefold() == name.strip().casefold()
               and calendar_source.chat_access(source, state) in calendar_source.READABLE]
    if len(matches) != 1:
        error = "calendar_name_ambiguous" if matches else "calendar_name_unknown"
        return CalendarChoice(name=name, error=error)
    return CalendarChoice(name=matches[0].name, source_id=matches[0].id, connection_ref=matches[0].connection_ref)


async def stated_destination(text, source_ids) -> CalendarChoice | None:
    # A direct reference such as "in the Work calendar" also works when the assistant
    # asks for a time in plain text or leaves calendar_name out of its later tool call.
    if not re.search(r"\b(?:calendar|kalender)\b", text, re.I):
        return None
    entries = await calendar_source.catalog(ids=source_ids)
    text = text.casefold()
    names = set()
    for source, _ in entries:
        name = re.escape(source.name.strip().casefold())
        literal = rf'["„“«]?{name}["”»]?'
        prefix = r"(?:in|into|to|on|im|für)\s+(?:(?:the|my|mein(?:em|en)?|den|dem|der|das)\s+)?"
        if re.search(rf'(?<!\w){prefix}(?:{literal}\s+(?:calendar|kalender)|(?:calendar|kalender)\s+{literal})(?!\w)', text):
            names.add(source.name.strip().casefold())
    if len(names) == 1:
        return named_choice(names.pop(), entries)
    if names:
        return CalendarChoice(name="", error="calendar_name_ambiguous")
    return None


async def choice_for_clarification(ctx, answer: str) -> CalendarChoice | None:
    if ctx.requested_calendar:
        return ctx.requested_calendar
    # A completed unrelated answer ends the pending request. A further scheduling
    # question may carry the same source through another clarification.
    details = re.search(r"\b(?:when|what time|date|duration|title|location|where|how long|wann|zeit|uhrzeit|datum|dauer|titel|ort|wie lange)\b", answer, re.I)
    if not details:
        return None
    creating = re.search(r"\b(?:create|schedule|book|arrange|add|erstelle\w*|plane\w*|trag\w*|anlegen|eintragen)\b", ctx.user_text, re.I)
    if ctx.calendar_choice or creating:
        return await stated_destination(ctx.user_text, ctx.calendar_source_ids) or ctx.calendar_choice
    return None
