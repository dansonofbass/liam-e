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
    excluded_source_ids: tuple[str, ...] = ()
    exclude_default: bool = False
    error: Literal["calendar_name_required", "calendar_name_ambiguous", "calendar_name_unknown", "calendar_appointment_ambiguous"] | None = None


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
    excluded_targets: frozenset[str] = frozenset()

    def mentions(self, name: str) -> bool:
        folded = name.strip().casefold()
        return folded in self.quoted_names or bool(re.search(r"(?<!\w)" + re.escape(folded) + r"(?!\w)", self.text.casefold()))

    def includes_id(self, source_id: str) -> bool:
        return bool(re.search(r"(?<![\w-])" + re.escape(source_id) + r"(?![\w-])", self.text))


def _selection_words(text: str, title: str | None) -> OwnerSelection:
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


_EXCLUSION = re.compile(r"(?<!\w)(?:do not|don['’]t|not|never|except(?: for)?|instead of|rather than|avoid|excluding|"
                        r"nicht|nie|keinesfalls|außer|statt|ohne)\b", re.I)
_DEFAULT_NAMES = frozenset(("default calendar", "standardkalender"))


def owner_selection(text: str, title: str | None = None, *, entries=()) -> OwnerSelection:
    """An exclusion applies to its named calendar operand, including quoted names."""
    masked = _QUOTED.sub(lambda match: " " * len(match.group()), text)
    if isinstance(title, str) and title.strip():
        masked = re.sub(r"\b(?:titled|called|named|mit (?:dem )?Titel|namens)\s+" + re.escape(title.strip()),
                        lambda match: " " * len(match.group()), masked, flags=re.I)
    exclusions = list(_EXCLUSION.finditer(masked))
    if not exclusions:
        return _selection_words(text, title)
    names = _DEFAULT_NAMES.union(value for source, _ in entries for value in (source.name.strip(), source.id) if value)
    choices = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    operand = re.compile(
        rf"\s*(?:(?:put|place|schedule|book|add|use|choose|pick|select|nutze|verwende|nimm)\s+"
        rf"(?:(?:it|this (?:event|appointment)|den Termin|ihn)\s+)?)?"
        rf"(?:{_PREFIX}|(?:the|my|den|dem|meinen|meinem)\s+)?(?:{_CALENDAR}\s+)?"
        rf"""["'“„‘‚«»]?(?P<name>{choices})(?![\w-])["'”’“‘»«]?(?:\s+{_CALENDAR}\b)?""", re.I)
    positive, blocked = [], set()
    offset = 0
    for exclusion in exclusions:
        if exclusion.start() < offset:
            continue
        # Match the original text so that a quoted calendar name can be checked.
        # Scan negation markers in the masked text so an event title cannot select a target.
        match = operand.match(text, exclusion.end())
        if not match:
            continue
        positive.append(text[offset:exclusion.start()])
        while match:
            blocked.add(match["name"].casefold())
            offset = match.end()
            join = re.match(r"\s+(?:or|oder|and|und)\s+", text[offset:], re.I)
            match = operand.match(text, offset + join.end()) if join else None
    selected = _selection_words(" ".join([*positive, text[offset:]]), title)
    return OwnerSelection(selected.text, selected.quoted_names, frozenset(blocked))


_ACTION = r"(?:put|schedule|create|book|add|arrange|make|set|plan[e]?|erstell[e]?|trag[e]?|leg[e]?|buch[e]?)"
_ARTICLE = r"(?:a|an|another|ein(?:e[nmr]?)?)"
_CLOCK = r"(?:[0-2]?\d[:.][0-5]\d|\d{1,2}\s*(?:am|pm|uhr))"
_NEXT_REQUEST = re.compile(
    r"(?:[.!?;]\s+|\n+|,\s*(?=separately|außerdem|separat)|\s+(?:and|und)\s+)"
    rf"(?=(?:(?:separately|also|then|außerdem|danach|separat)[, ]+)*{_ACTION}\b)"
    # A shared scheduling verb can introduce another timed appointment.
    rf"|(?P<shared>\s+(?:and|und)\s+)(?={_ARTICLE}\s+(?:{_CLOCK}\b|[^,;.!?\n]+?\s+(?:at|um)\s+{_CLOCK}\b))", re.I)


def appointment_parts(text: str) -> list[str]:
    """Split independent requests outside quoted event text, keeping alternatives together."""
    masked = _QUOTED.sub(lambda match: " " * len(match.group()), text)
    parts = []
    offset = 0
    for boundary in _NEXT_REQUEST.finditer(masked):
        if boundary["shared"] and not (re.match(rf"{_ARTICLE}\s+{_CLOCK}\b", masked[boundary.end():], re.I)
                or re.search(rf"(?:\b{_CALENDAR}|\b{_CLOCK})$", masked[offset:boundary.start()], re.I)):
            continue
        # "Put it in Work" after a sentence about the review still describes that review.
        if re.match(r"(?:put|schedule|book|set|plane|buche|trage)\s+(?:it|this one|that one|ihn|diesen Termin)\b",
                    masked[boundary.end():], re.I):
            continue
        if part := text[offset:boundary.start()].strip():
            parts.append(part)
        offset = boundary.end()
    return [*parts, text[offset:].strip()]


def appointment_part(parts: list[str], title, excerpt) -> str | None:
    title_matches = []
    if isinstance(title, str) and title.strip():
        pattern = r"(?<!\w)" + re.escape(title.strip().casefold()) + r"(?!\w)"
        title_matches = [part for part in parts if re.search(pattern, part.casefold())]
    if excerpt is None:
        if len(parts) == 1:
            return parts[0]
        return title_matches[0] if len(title_matches) == 1 else None
    if not isinstance(excerpt, str):
        return None
    # The whole clause is required: a model cannot discard a disjunction or use
    # another appointment's calendar when the title identifies a different clause.
    matches = [part for part in parts if part.strip(" .!?;") == excerpt.strip(" .!?;")]
    if len(matches) != 1 or (title_matches and matches[0] not in title_matches):
        return None
    return matches[0]


def _new_appointment(text: str) -> bool:
    explicit = r"\b(?:another|different|new|weiteren?|andere[nmrs]?|neue[nmrs]?)\s+(?:appointment|event|meeting|termin)\b"
    fresh = (r"\b(?:create|schedule|book|arrange|add|erstelle|plane)\s+"
             r"(?!(?:it|this|that|the|den|dem|das|ihn|diesen|es|at|for|on|um|am|für|today|tomorrow|heute|morgen)\b)\w+")
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
        return CalendarChoice.model_validate(data) if data and not _new_appointment(owner_selection(appointment_parts(text)[0]).text) else None
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


def _calendar_alternatives(text: str, entries) -> bool:
    disjunctions = list(re.finditer(r"\b(?:or|oder)\b", text, re.I))
    if not disjunctions:
        return False
    names = {source.name.strip() for source, _ in entries if source.name.strip()}
    names.update(("default calendar", "Standardkalender"))
    names_pattern = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    determiner = r"(?:(?:the|my|den|dem|meinen|meinem)\s+)?"
    operand = rf"(?:{_PREFIX}|{determiner})(?:{_CALENDAR}\s+)?(?P<name>{names_pattern})(?:\s+{_CALENDAR})?"
    for join in disjunctions:
        left = text[:join.start()].rstrip()
        right = text[join.end():].lstrip()
        first = re.search(rf"(?<![\w-]){operand}$", left, re.I)
        second = re.match(rf"{operand}(?![\w-])", right, re.I)
        if first and second and first["name"].casefold() != second["name"].casefold():
            words = first[0] + " " + second[0]
            if (re.search(rf"\b{_CALENDAR}\b|\bstandardkalender\b", words, re.I)
                    or re.match(_PREFIX, first[0], re.I)
                    or (first.start() == 0 and not right[second.end():].strip(" .?!"))):
                return True
    return False


def _affirmative_destination(selection: OwnerSelection, entries, previous: CalendarChoice | None) -> CalendarChoice | None:
    # A direct reference such as "in the Work calendar" also works when the assistant
    # asks for a time in plain text or leaves calendar_name out of its later tool call.
    text = selection.text
    if not text.strip() and not selection.quoted_names:
        return None
    use_default = bool(_DEFAULT.search(text))
    if _calendar_alternatives(text, entries):
        return CalendarChoice(error="calendar_name_ambiguous")
    folded = text.casefold()
    names = set(selection.quoted_names)
    for source, _ in entries:
        name = re.escape(source.name.strip().casefold())
        calendar_phrase = rf'{_PREFIX}(?:{name}\s+{_CALENDAR}|{_CALENDAR}\s+{name})(?!\w)'
        directive = rf'(?:use|choose|pick|nutze|nimm|verwende)\s+(?:(?:the|den)\s+)?{name}(?=\s*(?:{_CALENDAR}\b|[,.;!?]|$))'
        if re.search(rf'(?<!\w)(?:{calendar_phrase}|{directive})', folded):
            names.add(source.name.strip().casefold())
    if use_default and not names:
        return CalendarChoice(use_default=True)
    if len(names) == 1 and not use_default:
        return named_choice(names.pop(), entries, selection)
    if names:
        return CalendarChoice(name="", error="calendar_name_ambiguous")
    identified = {source.name for source, _ in entries if selection.includes_id(source.id)
                  and (selection.mentions(source.name) or previous and previous.name.casefold() == source.name.casefold())}
    if len(identified) == 1:
        return named_choice(identified.pop(), entries, selection)
    if identified:
        return CalendarChoice(error="calendar_name_ambiguous")
    return None


def stated_destination(selection: OwnerSelection, entries, previous: CalendarChoice | None) -> CalendarChoice | None:
    target = _affirmative_destination(selection, entries, previous)
    excluded = selection.excluded_targets
    if not excluded:
        return target
    blocked = {source.id for source, _ in entries if source.id.casefold() in excluded or source.name.strip().casefold() in excluded}
    default_blocked = bool(_DEFAULT_NAMES & excluded)
    if not blocked and not default_blocked:
        return target
    if not target and previous:
        blocked.update(previous.excluded_source_ids)
        default_blocked |= previous.exclude_default
        if previous.source_id and previous.source_id not in blocked:
            target = previous
    choice = target or CalendarChoice(use_default=True)
    return choice.model_copy(update={"excluded_source_ids": tuple(sorted(blocked)), "exclude_default": default_blocked})


async def choice_for_clarification(ctx, answer: str) -> CalendarChoice | None:
    parts = appointment_parts(ctx.user_text)
    unfinished = [part for part in parts if part not in ctx.completed_calendar_requests]
    if not unfinished:
        return None
    details = re.search(r"\b(?:when|what time|date|duration|title|location|where|how long|wann|zeit|uhrzeit|datum|dauer|titel|ort|wie lange)\b", answer, re.I)
    asking = "?" in answer or (details and re.search(r"\b(?:please|tell me|i need|bitte|nenne|ich brauche)\b", answer, re.I))
    if not any(part in ctx.calendar_targets for part in unfinished) and not asking:
        return None
    creating = re.search(r"\b(?:create|schedule|book|arrange|add|put|set up|make|plan[e]?|erstell[e]?|"
                         r"trag[e]?|leg[e]?|buch[e]?|anlegen|eintragen)\b", owner_selection(ctx.user_text).text, re.I)
    if not (ctx.calendar_targets or ctx.calendar_choice or creating):
        return None
    entries = await calendar_source.catalog(ids=ctx.calendar_source_ids)
    choices = []
    for part in unfinished:
        inherited = ctx.calendar_choice if part == parts[0] else None
        choice = ctx.calendar_targets.get(part) or stated_destination(owner_selection(part, entries=entries), entries, inherited) or inherited
        choices.append(choice)
    # A follow-up containing only a time cannot choose between unfinished
    # appointments with different targets. Ask the owner to specify the target.
    if any(choice != choices[0] for choice in choices[1:]):
        return CalendarChoice(error="calendar_appointment_ambiguous")
    return choices[0]
