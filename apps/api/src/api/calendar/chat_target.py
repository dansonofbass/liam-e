"""Server-owned target of one appointment awaiting clarification."""

import json
import re
from dataclasses import dataclass
from typing import Literal

from db.accessors import calendar_source
from pydantic import BaseModel


class CalendarChoice(BaseModel):
    name: str = ""
    use_default: bool = False
    source_id: str | None = None
    connection_ref: str | None = None
    error: Literal["calendar_name_ambiguous", "calendar_name_unknown"] | None = None


_QUOTED = re.compile(r""""[^"]*"|“[^”]*”|„[^“]*“|‘[^’]*’|‚[^‘]*‘|«[^»]*»|»[^«]*«|(?<!\w)'[^']*'(?!\w)""")
_PREFIX = r"(?:in|into|to|on|im|für)\s+(?:(?:the|my|mein(?:em|en)?|den|dem|der|das)\s+)?"
_CALENDAR = r"(?:calendar|kalender)"
_DEFAULT = re.compile(
    r"\b(?:use|choose|pick|in|into|on|to)\s+(?:(?:my|the)\s+)?default calendar\b"
    r"|\b(?:nimm|nutze|verwende|im|in|auf|zum|den)\s+(?:doch\s+)?(?:(?:meinen|meinem|den|dem)\s+)?standardkalender\b", re.I)


@dataclass(frozen=True)
class OwnerSelection:
    text: str
    quoted_names: tuple[str, ...]

    def mentions(self, name: str) -> bool:
        folded = name.strip().casefold()
        return folded in self.quoted_names or bool(re.search(r"(?<!\w)" + re.escape(folded) + r"(?!\w)", self.text.casefold()))

    def includes_id(self, source_id: str) -> bool:
        return bool(re.search(r"(?<![\w-])" + re.escape(source_id) + r"(?![\w-])", self.text))


def owner_selection(text: str, title: str | None = None) -> OwnerSelection:
    """Quoted descriptions are content. A quoted destination is one exact name."""
    names = []

    def quoted(match):
        before, after = text[:match.start()], text[match.end():]
        before_name = re.search(rf"\b{_PREFIX}{_CALENDAR}\s+$", before, re.I)
        after_name = re.search(rf"\b{_PREFIX}$", before, re.I) and re.match(rf"\s+{_CALENDAR}\b", after, re.I)
        if before_name or after_name:
            names.append(match.group()[1:-1].strip().casefold())
        return " "

    text = _QUOTED.sub(quoted, text)
    if isinstance(title, str) and title.strip():
        text = re.sub(r"\b(?:titled|called|named|mit (?:dem )?Titel|namens)\s+" + re.escape(title.strip()), " ", text, flags=re.I)
    return OwnerSelection(text, tuple(names))


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
        return CalendarChoice.model_validate(data) if data and not _new_appointment(owner_selection(text).text) else None
    except (AttributeError, TypeError, ValueError):
        return None


def named_choice(name, entries, selection: OwnerSelection):
    matches = [source for source, state in entries if source.name.strip().casefold() == name.strip().casefold()
               and calendar_source.chat_access(source, state) in calendar_source.READABLE]
    identified = [source for source in matches if selection.includes_id(source.id)]
    if identified:
        matches = identified
    if len(matches) != 1:
        error = "calendar_name_ambiguous" if matches else "calendar_name_unknown"
        return CalendarChoice(name=name, error=error)
    return CalendarChoice(name=matches[0].name, source_id=matches[0].id, connection_ref=matches[0].connection_ref)


def stated_destination(selection: OwnerSelection, entries, previous: CalendarChoice | None) -> CalendarChoice | None:
    # A direct reference such as "in the Work calendar" also works when the assistant
    # asks for a time in plain text or leaves calendar_name out of its later tool call.
    text = selection.text
    use_default = bool(_DEFAULT.search(text))
    identified = [source for source, _ in entries if selection.includes_id(source.id)
                  and (selection.mentions(source.name) or previous and previous.name.casefold() == source.name.casefold())]
    if identified:
        if len(identified) != 1 or use_default:
            return CalendarChoice(error="calendar_name_ambiguous")
        return named_choice(identified[0].name, entries, selection)
    if not use_default and not selection.quoted_names and not re.search(r"\b(?:calendar|kalender)\b", text, re.I):
        return None
    folded = text.casefold()
    names = set(selection.quoted_names)
    for source, _ in entries:
        name = re.escape(source.name.strip().casefold())
        if re.search(rf'(?<!\w){_PREFIX}(?:{name}\s+{_CALENDAR}|{_CALENDAR}\s+{name})(?!\w)', folded):
            names.add(source.name.strip().casefold())
    if use_default and not names:
        return CalendarChoice(use_default=True)
    if len(names) == 1 and not use_default:
        return named_choice(names.pop(), entries, selection)
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
        entries = await calendar_source.catalog(ids=ctx.calendar_source_ids)
        return stated_destination(owner_selection(ctx.user_text), entries, ctx.calendar_choice) or ctx.calendar_choice
    return None
