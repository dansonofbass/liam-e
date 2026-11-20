"""Server-owned target of one appointment awaiting clarification."""

import json
import re
from dataclasses import dataclass
from typing import Literal

from db.accessors import calendar_settings, calendar_source
from pydantic import BaseModel


class CalendarOption(BaseModel):
    name: str = ""
    use_default: bool = False
    source_id: str | None = None
    connection_ref: str | None = None

    @classmethod
    def for_source(cls, source):
        return cls(name=source.name, source_id=source.id, connection_ref=source.connection_ref)


class AppointmentCalendar(CalendarOption):
    offered: tuple[CalendarOption, ...] = ()
    appointment_subject: str = ""
    excluded_source_ids: tuple[str, ...] = ()
    exclude_default: bool = False
    error: Literal["calendar_name_required", "calendar_name_ambiguous", "calendar_name_unknown", "calendar_appointment_ambiguous"] | None = None

    def bind_default(self, source):
        if self.exclude_default or source.id in self.excluded_source_ids:
            return self.model_copy(update={"error": "calendar_name_required"})
        return self.model_copy(update={"source_id": source.id, "connection_ref": source.connection_ref})


class CalendarChoice(AppointmentCalendar):
    sequence_id: str | None = None
    appointments: tuple[AppointmentCalendar, ...] = ()
    focused_index: int | None = None

    def appointment(self) -> AppointmentCalendar:
        return AppointmentCalendar(**self.model_dump(include=set(AppointmentCalendar.model_fields)))


_QUOTED = re.compile(r""""[^"]*"|“[^”]*”|„[^“]*“|‘[^’]*’|‚[^‘]*‘|«[^»]*»|»[^«]*«|(?<!\w)'[^']*'(?!\w)""")
_DETERMINER = r"(?:(?:the|my|mein(?:em|en)?|den|dem|der|das)\s+)?"
_PREFIX = rf"(?:in|into|to|on|im|für)\s+{_DETERMINER}"
_SELECT = r"(?:use|choose|pick|select|nutze|verwende|nimm|wähle)"
_DESTINATION_PREFIX = rf"(?:{_PREFIX}|{_SELECT}\s+{_DETERMINER})"
_CALENDAR = r"(?:calendar|kalender)"
_NAME_WORD = (r"(?!(?:the|an?|my|den|dem|der|die|das|ein(?:e[nrms]?)?|in|im|into|on|for|at|from|to|am|um|für|with|mit|"
              r"today|tomorrow|heute|morgen|instead|statt|please|bitte|eintragen|anlegen|"
              r"and|und|or|oder|calendar|kalender)\b)\w+(?:[-&/'’]\w+)*")
_NAME_FIRST = re.compile(rf"(?<!\w){_DESTINATION_PREFIX}(?P<name>{_NAME_WORD}(?:\s+(?:(?:&|and|und)\s+)?{_NAME_WORD})*)\s+{_CALENDAR}\b", re.I)
_CALENDAR_LEAD = rf"(?<!\w){_DESTINATION_PREFIX}{_CALENDAR}\b"
_DAY_OR_PERIOD = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week(?:end)?|month|year|"
                  r"morning|afternoon|evening|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|"
                  r"woche(?:nende)?|monat|jahr|vormittag|nachmittag|abend)")
_RELATIVE_DAY = r"(?:next|this|coming|following|last|every|nächste[nrms]?|diese[nrms]?|kommende[nrms]?)"
_TIME_PREPOSITION = r"(?:on|at|after|before|during|between|from|until|am|um|nach|vor|ab|bis|zwischen)"
_MONTH = r"(?:january|januar|february|februar|march|märz|april|may|mai|june|juni|july|juli|august|september|october|oktober|november|december|dezember)"
_TIME_VALUE = rf"(?:{_DAY_OR_PERIOD}|{_MONTH}|today|tomorrow|heute|morgen|noon|midnight|mittag|mitternacht|\d+[./:-]\d+|\d+\s*(?:am|pm|uhr))"
_DATE_TAIL = (rf"(?:(?:(?:{_RELATIVE_DAY}|{_TIME_PREPOSITION})\s+)*{_TIME_VALUE}\b|"
              rf"{_TIME_PREPOSITION}\s+(?:\d+|the|a|an|my|dem|der|den|einem|meinem)\b)")
_SCHEDULING_OPTION = re.compile(rf"{_DATE_TAIL}(?:\s+{_DATE_TAIL})*", re.I)
_GENERIC_CALENDAR_DATE = re.compile(rf"{_CALENDAR_LEAD}(?=\s+{_DATE_TAIL})", re.I)
_NAME_CONTINUATION = rf"\s+(?!{_DATE_TAIL})(?:&\s+)?{_NAME_WORD}"
_CALENDAR_FIRST = re.compile(rf"{_CALENDAR_LEAD}\s+(?P<name>(?:{_TIME_PREPOSITION}\s+)?{_NAME_WORD}(?:{_NAME_CONTINUATION})*)", re.I)
_CALENDAR_DAY = re.compile(rf"{_CALENDAR_LEAD}\s+(?P<day>(?:(?:on|am)\s+)?(?:{_RELATIVE_DAY}\s+)?"
                           rf"(?:{_DAY_OR_PERIOD}|today|tomorrow|heute|morgen))\b", re.I)
_DEFAULT = re.compile(
    r"\b(?:use|choose|pick|in|into|on|to)\s+(?:(?:my|the)\s+)?default calendar\b"
    r"|\b(?:nimm|nutze|verwende|im|in|auf|zum|den)\s+(?:doch\s+)?(?:(?:meinen|meinem|den|dem)\s+)?standardkalender\b", re.I)


@dataclass(frozen=True)
class OwnerSelection:
    text: str
    quoted_names: tuple[str, ...]
    excluded_targets: frozenset[str] = frozenset()
    alternatives_text: str = ""

    def mentions(self, name: str) -> bool:
        folded = name.strip().casefold()
        return folded in self.quoted_names or bool(re.search(r"(?<!\w)" + re.escape(folded) + r"(?!\w)", self.text.casefold()))

    def includes_id(self, source_id: str) -> bool:
        return bool(re.search(r"(?<![\w-])" + re.escape(source_id) + r"(?![\w-])", self.text))

    def is_name_answer(self, name: str) -> bool:
        key = name.strip().casefold()
        operand = rf"(?:{_CALENDAR}\s+)?{re.escape(key)}(?![\w-])(?:\s+{_CALENDAR})?"
        return bool(re.fullmatch(rf"(?:please\s+|bitte\s+)?{operand}(?:,?\s+(?:please|bitte))?[.!?]?", self.text.strip().casefold()))

    def names_target(self, name: str) -> bool:
        key = name.strip().casefold()
        operand = rf"(?:{_CALENDAR}\s+)?{re.escape(key)}(?![\w-])(?:\s+{_CALENDAR}\b|(?!{_NAME_CONTINUATION}))"
        return (key in self.quoted_names or self.is_name_answer(name)
                or bool(re.search(rf"(?<!\w){_DESTINATION_PREFIX}{operand}", self.text.casefold())))


def _without_scheduling_days(words: str, entries) -> str:
    def replace(match):
        day = match["day"].casefold()
        tail = words[match.start("day"):].casefold()
        # A complete source such as "Monday Shifts" can start with a day.
        # A name matching only part of "on Thursday" cannot select a calendar.
        for source, _ in entries:
            name = source.name.strip().casefold()
            if len(name) >= len(day) and re.match(re.escape(name) + r"(?![\w-])", tail):
                return match[0]
        return " "
    return _CALENDAR_DAY.sub(replace, words)


def _selection_words(text: str, title: str | None, entries) -> OwnerSelection:
    """Quoted descriptions are content. A quoted destination is one exact name."""
    names = []

    def quoted(match):
        before, after = text[:match.start()], text[match.end():]
        before_name = re.search(rf"{_CALENDAR_LEAD}\s+$", before, re.I)
        after_name = re.search(rf"\b{_DESTINATION_PREFIX}$", before, re.I) and re.match(rf"\s+{_CALENDAR}\b", after, re.I)
        if before_name or after_name:
            names.append(match.group()[1:-1].strip().casefold())
        return " "

    if isinstance(title, str) and title.strip():
        text = re.sub(r"\b(?:titled|called|named|mit (?:dem )?Titel|namens)\s+" + re.escape(title.strip()), " ", text, flags=re.I)
    alternatives = text
    if re.search(r"\b(?:or|oder)\b", text, re.I):
        known = {source.name.strip().casefold() for source, _ in entries} | _DEFAULT_NAMES
        # Keep a boundary for other quoted text so its neighbouring list items cannot collapse.
        alternatives = _QUOTED.sub(lambda match: match[0][1:-1] if match[0][1:-1].strip().casefold() in known else "\ufffc", text)
    positive = _QUOTED.sub(quoted, text)

    return OwnerSelection(_without_scheduling_days(positive, entries), tuple(names),
                          alternatives_text=_without_scheduling_days(alternatives, entries))


_EXCLUSION = re.compile(r"(?<!\w)(?:do not|don['’]t|not|never|except(?: for)?|instead of|rather than|avoid|excluding|"
                        r"nicht|nie|keinesfalls|außer|statt|ohne)\b", re.I)
_TARGET_VERB = (rf"(?:(?:put|place|schedule|book|add|{_SELECT})\s+"
                r"(?:(?:it|this (?:event|appointment)|den Termin|ihn)\s+)?)?")
_NEGATIVE_CALENDAR_PREFIX = re.compile(rf"{_EXCLUSION.pattern}\s*{_TARGET_VERB}$", re.I)
_DEFAULT_NAMES = frozenset(("default calendar", "standardkalender"))


_LOCATION = re.compile(r"\b(?:location|venue|place|ort|veranstaltungsort|treffpunkt)\s*"
                       r"(?:(?:set|changed|geändert|gesetzt)\s+)?(?:[:=]|\b(?:to|as|is|auf|ist)\b)\s*", re.I)
_FIELD_END = re.compile(r"[,;.!?\n]|\b(?:and|und|but|aber)\s+(?=(?:(?:please|bitte)\s+)?"
                        r"(?:put|use|choose|schedule|create|verwende|nimm|plane|erstelle)\b)", re.I)
_CALENDAR_INSTRUCTION = re.compile(rf"{_CALENDAR_LEAD}|(?<!\w){_SELECT}\s+", re.I)


def _without_locations(text: str, location: str | None) -> str:
    # Keep a quoted value as one opaque word so a following calendar directive
    # still has its operand, without interpreting instructions inside the quote.
    masked = _QUOTED.sub(lambda match: "x".ljust(len(match[0])), text)
    fields = list(_LOCATION.finditer(masked))
    if isinstance(location, str) and location.strip():
        fields.extend(re.finditer(r"\b(?:at|bei)\s+(?=" + re.escape(location.strip()) + r"(?!\w))", masked, re.I))
    for field in reversed(sorted(fields, key=lambda match: match.start())):
        start = field.end()
        if isinstance(location, str) and text[start:start + len(location)].casefold() == location.casefold():
            start += len(location)
        boundary = _FIELD_END.search(masked, start)
        end = boundary.start() if boundary else len(text)
        for pattern in (_NAME_FIRST, _CALENDAR_INSTRUCTION):
            if match := pattern.search(masked, start, end):
                calendar_start = match.start()
                # The negation before a separately named calendar belongs with
                # its destination, even without punctuation after the venue.
                prefix = _NEGATIVE_CALENDAR_PREFIX.search(masked, start, calendar_start)
                end = prefix.start() if prefix else calendar_start
        text = text[:field.start()] + " " * (end - field.start()) + text[end:]
    return text


def _declared_names(text: str) -> set[str]:
    # This fallback infers names absent from the catalog. A scheduling phrase
    # after "my calendar" is not evidence of an unknown calendar name.
    text = _GENERIC_CALENDAR_DATE.sub(" ", text)
    return {match["name"].strip().casefold() for pattern in (_NAME_FIRST, _CALENDAR_FIRST) for match in pattern.finditer(text)}


def owner_selection(text: str, title: str | None = None, *, entries=(), location: str | None = None) -> OwnerSelection:
    """An exclusion applies to its named calendar operand, including quoted names."""
    text = _without_locations(text, location)
    masked = _QUOTED.sub(lambda match: " " * len(match.group()), text)
    if isinstance(title, str) and title.strip():
        masked = re.sub(r"\b(?:titled|called|named|mit (?:dem )?Titel|namens)\s+" + re.escape(title.strip()),
                        lambda match: " " * len(match.group()), masked, flags=re.I)
    exclusions = list(_EXCLUSION.finditer(masked))
    if not exclusions:
        return _selection_words(text, title, entries)
    names = _DEFAULT_NAMES.union(_declared_names(masked), (value for source, _ in entries for value in (source.name.strip(), source.id) if value))
    choices = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    operand = re.compile(
        rf"\s*{_TARGET_VERB}"
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
    selected = _selection_words(" ".join([*positive, text[offset:]]), title, entries)
    return OwnerSelection(selected.text, selected.quoted_names, frozenset(blocked), selected.alternatives_text)


_ACTION = r"(?:put|schedule|create|book|add|arrange|make|set up|set|plane?|erstelle?|trage?|lege?|buche?)"
_ARTICLE = r"(?:a|an|another|ein(?:e[nmr]?)?)"
_CLOCK = r"(?:[0-2]?\d[:.][0-5]\d|\d{1,2}\s*(?:am|pm|uhr))"
_NEXT_REQUEST = re.compile(
    r"(?:[.!?;]\s+|\n+|,\s*(?=separately|außerdem|separat)|\s+(?:and|und)\s+)"
    rf"(?=(?:(?:separately|also|then|außerdem|danach|separat)[, ]+)*{_ACTION}\b)"
    # A shared scheduling verb can introduce another timed appointment.
    rf"|(?P<shared>\s+(?:and|und)\s+)(?={_ARTICLE}\s+(?:{_CLOCK}\b|[^,;.!?\n]+?\s+(?:at|um)\s+{_CLOCK}\b))", re.I)


_TIME_DETAIL = re.compile(rf"(?<!\w)(?:{_DATE_TAIL}|{_CLOCK}|(?:at|um)\s+\w+|(?:hours?|minutes?|stunden?|minuten)\b)", re.I)


def _split_named_times(part: str, appointments, divider) -> list[str]:
    masked = _QUOTED.sub(lambda match: " " * len(match[0]), part)
    boundaries = list(divider.finditer(masked))
    clauses = []
    start = 0
    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(part)
        left, right = masked[start:boundary.start()], masked[boundary.end():end]
        if _mentioned_appointments(appointments, left) and _TIME_DETAIL.search(left) and _TIME_DETAIL.search(right):
            clauses.append(part[start:boundary.start()].strip())
            start = boundary.end()
    return [*clauses, part[start:].strip()]


def appointment_parts(text: str, previous: CalendarChoice | None = None) -> list[str]:
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
    parts.append(text[offset:].strip())
    subjects = {item.appointment_subject for item in previous.appointments if item.appointment_subject} if previous else set()
    if not subjects:
        return parts
    names = "|".join(re.escape(subject) for subject in sorted(subjects, key=len, reverse=True))
    divider = re.compile(r"(?:[,;.!?]\s*(?:(?:and|und)\s+)?|\n+|\s+(?:and|und)\s+)"
                         rf"(?=(?:(?:the|der|die|das)\s+)?(?:{names})(?![\w-]))", re.I)
    return [clause for part in parts for clause in _split_named_times(part, previous.appointments, divider)]


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


def _appointment_subject(text: str) -> str:
    masked = _QUOTED.sub(lambda match: " " * len(match[0]), text)
    command = re.search(rf"\b{_ACTION}\b", masked, re.I)
    if not command:
        return ""
    rest = text[command.end():].strip()
    rest = re.sub(r"^(?:a|an|the|its|den|das|der|die|ein(?:e[nmrs]?)?)\s+", "", rest, flags=re.I)
    if quoted := _QUOTED.match(rest):
        return " ".join(quoted.group()[1:-1].casefold().split())
    if re.match(r"(?:start(?:ing)? time|end time|time|date|duration|title|location|description|"
                r"startzeit|endzeit|uhrzeit|datum|dauer|titel|ort|beschreibung)\b"
                r"(?=\s*(?:[:=]|\d)|\s+(?:to|as|at|for|on|of|auf|um|für)\b|$)", rest, re.I):
        return ""
    modifier = r"\b(?:in|into|on|to|for|at|from|im|am|um|für|tomorrow|today|heute|morgen)\b|[,;.!?]"
    subject = re.split(modifier, rest, maxsplit=1, flags=re.I)[0].strip()
    if re.match(r"(?:it|this|that|ihn|es|diesen)\b", subject, re.I):
        return ""
    return " ".join(subject.casefold().split())


def _mentioned_appointments(appointments, text):
    folded = text.casefold()
    return [item for item in appointments if item.appointment_subject and
            re.search(r"(?<!\w)" + re.escape(item.appointment_subject) + r"(?!\w)", folded)]


def pending_for_request(previous: CalendarChoice | None, text: str, title=None, *, first=True, selected_source_id=None,
                        use_focus=True) -> CalendarChoice | None:
    if not previous:
        return None
    subject = _appointment_subject(text)
    proposed = " ".join(title.casefold().split()) if isinstance(title, str) else ""
    if previous.appointments:
        if subject:
            matches = [item for item in previous.appointments if item.appointment_subject == subject]
        else:
            matches = _mentioned_appointments(previous.appointments, text)
            if not matches and first and previous.appointment_subject and (use_focus or selected_source_id):
                matches = [item for item in previous.appointments if item.appointment_subject == previous.appointment_subject]
        if selected_source_id:
            candidates = matches or (previous.appointments if not subject else ())
            if len({item.appointment_subject for item in candidates}) == 1:
                matches = [item for item in candidates if item.source_id == selected_source_id] or matches
        index = previous.focused_index
        if use_focus and first and index is not None and 0 <= index < len(previous.appointments):
            focused = previous.appointments[index]
            if (not subject and not matches) or (len(matches) > 1 and focused in matches):
                matches = [focused]
        if len(matches) == 1:
            if proposed != matches[0].appointment_subject and any(item.appointment_subject == proposed for item in previous.appointments):
                return previous
            return CalendarChoice(**matches[0].model_dump(), sequence_id=previous.sequence_id)
        if matches:
            return previous
    elif subject and subject == previous.appointment_subject:
        return previous
    if not first:
        return None
    explicit = r"\b(?:another|different|new|weiteren?|andere[nmrs]?|neue[nmrs]?)\s+(?:appointment|event|meeting|termin)\b"
    words = owner_selection(text).text
    if re.search(explicit, words, re.I):
        return None
    # "Set/make/put ..." can fill a field of the pending appointment. Only a
    # separately identifiable appointment should acquire a fresh default.
    if not subject:
        return previous
    command = re.search(rf"\b{_ACTION}\b", words, re.I)
    create = command and command[0].casefold() in {"schedule", "create", "book", "arrange", "add", "set up", "erstelle", "plane", "buche"}
    return None if create or (proposed and proposed == subject) else previous


async def appointment_destination(previous, part, title=None, *, first, selection, entries):
    """Resolve the unfinished appointment and the owner's destination from the same evidence."""
    choice = pending_for_request(previous, part, title, first=first, use_focus=False)
    target = await stated_destination(selection, entries, None if choice and choice.appointments else choice)
    if not choice or not choice.appointments:
        return choice, target
    if target is None:
        names = {source.name for source, _ in entries if selection.is_name_answer(source.name)}
        if len(names) == 1:
            target = named_choice(names.pop(), entries, selection)
    if target and target.use_default and not target.error:
        default_id = (await calendar_settings.get()).default_source_id
        source = next((source for source, _ in entries if source.id == default_id), None)
        if source:
            target = target.bind_default(source)
    if target and target.source_id and not target.error:
        choice = pending_for_request(previous, part, title, first=first, selected_source_id=target.source_id, use_focus=False)
    elif target is None:
        choice = pending_for_request(previous, part, title, first=first)
    return choice, target


def previous_choice(history, user_id: str, contexts) -> CalendarChoice | None:
    # A confirmation in another tab can publish a card after the assistant's
    # question, or even after this turn's user message was inserted.
    turn = (row for row in reversed(history) if row.role != "proposal")
    user, reply = next(turn, None), next(turn, None)
    if user is None or user.id != user_id or reply is None:
        return None
    if reply.role != "assistant" or reply.tool_payload_json or reply.stopped or not reply.extras_json:
        return None
    previous_user = next((row for row in turn if row.role == "user"), None)
    context = contexts.get(reply.context_id)
    if not previous_user or previous_user.context_id != reply.context_id or not context or context.revoked:
        return None
    try:
        data = json.loads(reply.extras_json).get("calendar_clarification")
        if not data:
            return None
        choice = CalendarChoice.model_validate(data)
        if choice.appointments:
            return choice
        subject = choice.appointment_subject or _appointment_subject(previous_user.content)
        return choice.model_copy(update={"appointment_subject": subject})
    except (AttributeError, TypeError, ValueError):
        return None


def named_choice(name, entries, selection: OwnerSelection, *, offered=()):
    key = name.strip().casefold()
    matches = [option for option in offered if option.name.strip().casefold() == key]
    if not matches:
        matches = [CalendarOption.for_source(source) for source, state in entries if source.name.strip().casefold() == key
                   and calendar_source.chat_access(source, state) in calendar_source.READABLE]
    identified = [option for option in matches if option.source_id and selection.includes_id(option.source_id)]
    if identified:
        matches = identified
    if len(matches) != 1 or not matches[0].source_id:
        error = "calendar_name_ambiguous" if matches else "calendar_name_unknown"
        return CalendarChoice(name=name, error=error, offered=tuple(matches))
    return CalendarChoice(**matches[0].model_dump())


_OR = re.compile(r"\b(?:or|oder)\b", re.I)
_LIST_SEPARATOR = r"(?:,\s*(?:(?:or|oder|and|und)\b)?|[/&]|\b(?:or|oder|and|und)\b)"
_CALENDAR_NOUN = re.compile(rf"\b{_CALENDAR}\b|\bstandardkalender\b", re.I)


def _calendar_list_end(text: str, members, names) -> int:
    """A completed calendar phrase can be followed by a separate event condition."""
    for index in range(len(members) - 1, -1, -1):
        member = members[index]
        if _CALENDAR_NOUN.search(member[0]):
            if index + 1 < len(members) and text[member.end():members[index + 1].start()].strip() == ",":
                tail = members[index + 1:]
                condition = text[tail[0].start():tail[-1].end()].strip()
                if (all(_SCHEDULING_OPTION.fullmatch(item[0]) for item in tail)
                        or re.fullmatch(r"rain\s+or\s+shine|bei\s+wind\s+und\s+wetter", condition, re.I)):
                    return index + 1
                # Unrecognized alternatives may be removed calendar names. A
                # comma or a change in capitalization does not settle the choice.
            break
        # A later named, quoted or explicitly selected option keeps the list
        # together, including any unavailable options before it.
        raw_name = member["name"]
        if (raw_name.casefold() in names or raw_name == "\ufffc"
                or re.match(_SELECT + r"\b", member[0], re.I)):
            break
    return len(members)


async def _calendar_alternatives(text: str, entries) -> tuple[set[str], bool]:
    """Read each contiguous list as a whole. An unknown member prevents elimination."""
    alternatives = set()
    if not _OR.search(text):
        return alternatives, True
    names = _DEFAULT_NAMES.union(source.name.strip().casefold() for source, _ in entries if source.name.strip())
    vocabulary = names
    if "," in text and _CALENDAR_NOUN.search(text):
        # A paused calendar can still be an option the owner named. Only its
        # label helps identify the list; access and bindings come from entries.
        folded = text.casefold()
        vocabulary = names.union(name for name in await calendar_source.configured_names() if name in folded)
    names_pattern = "|".join(re.escape(name) for name in sorted(vocabulary, key=len, reverse=True))
    # An unavailable name still occupies its position in the owner's list.
    # Preserve literal catalog names with punctuation and opaque quoted members.
    word = rf"(?!{_SELECT}\b){_NAME_WORD}"
    member_name = rf"(?:(?:{names_pattern})(?!{_NAME_CONTINUATION})|{word}(?:\s+{word})*|\ufffc)"
    operand = rf"(?:{_DESTINATION_PREFIX}|{_DETERMINER})(?:{_CALENDAR}\s+)?(?P<name>{member_name})(?:\s+{_CALENDAR})?"
    groups = []
    for member in re.finditer(rf"(?<![\w-]){operand}(?![\w-])", text, re.I):
        separator = text[groups[-1][-1].end():member.start()].strip() if groups else ""
        if (not re.fullmatch(_LIST_SEPARATOR, separator, re.I)
                or (separator == "," and re.match(_SELECT + r"\b", member[0], re.I))):
            groups.append([])
        groups[-1].append(member)

    complete = True
    for members in groups:
        first = members[0]
        before = text[:first.start()]
        calendar_field = re.search(rf"\b(?:for|für)\s+{_DETERMINER}{_CALENDAR}\s*[:,]?\s*$", before, re.I)
        selection_verb = re.match(_SELECT + r"\b", first[0], re.I)
        end = _calendar_list_end(text, members, vocabulary)
        group = members[:end]
        last = group[-1]
        after = text[last.end():]
        left = re.search(rf"{_LIST_SEPARATOR}\s*$", before, re.I)
        right = re.match(rf"\s*{_LIST_SEPARATOR}", after, re.I) if end == len(members) else None
        joiners = " ".join(text[a.end():b.start()] for a, b in zip(group, group[1:]))
        if not any(_OR.search(value) for value in (joiners, left[0] if left else "", right[0] if right else "")):
            continue
        qualified = re.match(_DESTINATION_PREFIX, first[0], re.I)
        phrase = text[first.start():last.end()]
        offered = {member["name"].casefold() for member in group}
        recognized = offered & names
        entire_reply = not before.strip() and not after.strip(" .?!")
        calendar_noun = _CALENDAR_NOUN.search(phrase)
        if not (calendar_noun or calendar_field or (recognized and (qualified or entire_reply))
                or (entire_reply and selection_verb)):
            continue
        alternatives.update(recognized)
        if not offered <= names or right or (left and not (qualified and left[0].strip() == ",")):
            complete = False
    return alternatives, complete


async def _affirmative_destination(selection: OwnerSelection, entries, previous: CalendarChoice | None) -> CalendarChoice | None:
    # A direct reference such as "in the Work calendar" also works when the assistant
    # asks for a time in plain text or leaves calendar_name out of its later tool call.
    text = selection.text
    if not text.strip() and not selection.quoted_names:
        return None
    use_default = bool(_DEFAULT.search(text))
    folded = text.casefold()
    alternatives, complete = await _calendar_alternatives(selection.alternatives_text, entries)
    if not complete:
        return CalendarChoice(error="calendar_name_ambiguous")
    use_default |= bool(alternatives & _DEFAULT_NAMES)
    names = set(selection.quoted_names) | (alternatives - _DEFAULT_NAMES)
    catalog = {source.name.strip().casefold() for source, _ in entries if source.name.strip()}
    if catalog:
        # Match one complete catalog name per destination. A shorter name can
        # itself be a source, e.g. both "On" and "On Call".
        operand = "(?P<name>" + "|".join(re.escape(name) for name in sorted(catalog, key=len, reverse=True)) + r")(?![\w-])"
        patterns = [
            rf"{_CALENDAR_LEAD}\s+{operand}(?!{_NAME_CONTINUATION})",
            rf"(?<!\w){_DESTINATION_PREFIX}{operand}\s+{_CALENDAR}\b",
            rf"(?<!\w){_SELECT}\s+{_DETERMINER}{operand}(?=\s*(?:[,.;!?]|$))",
        ]
        if selection.excluded_targets:
            patterns.append(rf"(?<!\w){_PREFIX}{operand}(?=\s*(?:[,.;!?]|$))")
        for pattern in patterns:
            names.update(match["name"] for match in re.finditer(pattern, folded))
    # The owner can explicitly name a paused, removed or unknown calendar. The
    # readable catalog cannot supply that name; only the owner's text can.
    if not use_default and not names:
        names.update(_declared_names(folded))
    if use_default and not names:
        return CalendarChoice(use_default=True)
    if len(names) == 1 and not use_default:
        return named_choice(names.pop(), entries, selection, offered=previous.offered if previous else ())
    if names:
        offered = []
        for name in sorted(names):
            option = named_choice(name, entries, selection)
            offered.extend(option.offered or (CalendarOption.model_validate(option.model_dump()),))
        if use_default:
            offered.append(CalendarOption(use_default=True))
        return CalendarChoice(error="calendar_name_ambiguous", offered=tuple(offered))
    identified = {source.name for source, _ in entries if selection.includes_id(source.id) and (
        previous and previous.name.casefold() == source.name.casefold()
        or source.id.casefold() != source.name.strip().casefold() and selection.mentions(source.name)
        or selection.names_target(source.name))}
    if len(identified) == 1:
        return named_choice(identified.pop(), entries, selection)
    if identified:
        return CalendarChoice(error="calendar_name_ambiguous")
    return None


async def stated_destination(selection: OwnerSelection, entries, previous: CalendarChoice | None) -> CalendarChoice | None:
    target = await _affirmative_destination(selection, entries, previous)
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
        if previous.error:
            remaining = tuple(option for option in previous.offered if option.name.casefold() not in excluded
                              and option.source_id not in blocked and not (option.use_default and default_blocked))
            if len(remaining) == 1 and (remaining[0].source_id or remaining[0].use_default):
                target = CalendarChoice(**remaining[0].model_dump())
            else:
                target = previous.model_copy(update={"offered": remaining})
        elif previous.source_id and previous.source_id not in blocked:
            target = previous
    # Only the owner's explicit choice of the default can override a named
    # destination. Exclusions by themselves constrain whichever source wins.
    choice = target or CalendarChoice()
    return choice.model_copy(update={"excluded_source_ids": tuple(sorted(blocked)), "exclude_default": default_blocked})


async def _question_appointment(appointments, question, selected, entries):
    mentioned = _mentioned_appointments(appointments, question)
    selection = owner_selection(question, entries=entries)
    target = await stated_destination(selection, entries, None)
    candidates = mentioned or appointments
    if target or _CALENDAR_NOUN.search(question):
        if not target or target.error or not target.source_id:
            return None
        matches = [item for item in candidates if item.source_id == target.source_id and item.connection_ref == target.connection_ref]
        return matches[0] if len(matches) == 1 else None
    if len(mentioned) == 1:
        return mentioned[0]
    # A calendar name can also be an ordinary word, as in "would work".
    bound_ids = {item.source_id for item in candidates}
    if any(source.id in bound_ids and (selection.names_target(source.name) or
           re.search(r"\bfor\s+(?:the\s+)?" + re.escape(source.name) + r"(?![\w-])", selection.text, re.I))
           for source, _ in entries):
        return None
    if re.search(r"\b(?:which (?:one|of|appointment)|welche[rnms]? (?:davon|termin)|other|andere[nrms]?)\b", question, re.I):
        return None
    if mentioned and not (selected in mentioned and re.search(r"\b(?:this|that|its|same|diese[nrms]?|dessen)\b", question, re.I)):
        return None
    return selected


async def _clarification(appointments: list[AppointmentCalendar], sequence_id: str | None, answer: str,
                         source_ids, entries, selected: AppointmentCalendar | None = None) -> CalendarChoice | None:
    if not appointments:
        return None
    if len(appointments) == 1:
        return CalendarChoice(**appointments[0].model_dump(), sequence_id=sequence_id)
    questions = " ".join(re.findall(r"[^.!?]*\?", answer))
    if not questions and re.search(r"\b(?:what time|when|how long|which|please tell|wann|wie lange|welche[rnms]?|bitte nenn\w*)\b", answer, re.I):
        questions = answer
    if questions:
        if entries is None:
            entries = await calendar_source.catalog(ids=source_ids)
        selected = await _question_appointment(appointments, questions, selected, entries)
    index = appointments.index(selected) if selected is not None else None
    return CalendarChoice(appointments=tuple(appointments), sequence_id=sequence_id, error="calendar_appointment_ambiguous",
                          focused_index=index, appointment_subject=selected.appointment_subject if selected else "")


async def choice_for_clarification(ctx, answer: str) -> CalendarChoice | None:
    parts = appointment_parts(ctx.user_text, ctx.calendar_choice)
    unfinished = [part for part in parts if part not in ctx.completed_calendar_requests]
    previous = ctx.calendar_choice
    entries = None
    continuations = dict(ctx.calendar_continuations)
    targets = dict(ctx.calendar_targets)
    for index, part in enumerate(parts):
        if part in continuations:
            continue
        if previous and previous.appointments:
            if entries is None:
                entries = await calendar_source.catalog(ids=ctx.calendar_source_ids)
            continuations[part], targets[part] = await appointment_destination(previous, part, first=index == 0,
                selection=owner_selection(part, entries=entries), entries=entries)
        else:
            continuations[part] = pending_for_request(previous, part, first=index == 0)
    sequence_id = ctx.calendar_sequence_id
    # Updating one previously unfinished appointment leaves its siblings bound
    # to their own targets, even when the assistant has just prepared its card.
    appointments = []
    if previous and any(continuations.values()):
        sequence_id = sequence_id or previous.sequence_id
        addressed = [choice.appointment() for choice in continuations.values() if choice and not choice.appointments]
        appointments.extend(item for item in previous.appointments if item not in addressed)
    if not unfinished:
        return await _clarification(appointments, sequence_id, answer, ctx.calendar_source_ids, entries)
    details = re.search(r"\b(?:when|what time|date|duration|title|location|where|how long|wann|zeit|uhrzeit|datum|dauer|titel|ort|wie lange)\b", answer, re.I)
    asking = "?" in answer or (details and re.search(r"\b(?:please|tell me|i need|bitte|nenne|ich brauche)\b", answer, re.I))
    if not any(part in ctx.calendar_targets for part in unfinished) and not asking:
        return None
    creating = re.search(r"\b(?:create|schedule|book|arrange|add|put|set up|make|plan[e]?|erstell[e]?|"
                         r"trag[e]?|leg[e]?|buch[e]?|anlegen|eintragen)\b", owner_selection(ctx.user_text).text, re.I)
    if not (ctx.calendar_targets or ctx.calendar_choice or creating):
        return None
    if entries is None:
        entries = await calendar_source.catalog(ids=ctx.calendar_source_ids)
    selected = None
    for part in unfinished:
        inherited = continuations[part]
        if inherited and inherited.appointments:
            continue
        if part not in targets:
            targets[part] = await stated_destination(owner_selection(part, entries=entries), entries, inherited)
        choice = targets[part] or inherited
        if entries and (choice is None or (not choice.source_id and not choice.error)):
            default_id = (await calendar_settings.get()).default_source_id
            default = next((source for source, state in entries if source.id == default_id
                            and calendar_source.chat_access(source, state) == "writable"), None)
            if default:
                choice = (choice or CalendarChoice()).bind_default(default)
        if choice or sequence_id or len(unfinished) > 1:
            binding = choice.appointment() if choice else AppointmentCalendar()
            binding.appointment_subject = (inherited.appointment_subject if inherited else "") or _appointment_subject(part)
            appointments.append(binding)
            if inherited and len(unfinished) == 1:
                selected = binding
    return await _clarification(appointments, sequence_id, answer, ctx.calendar_source_ids, entries, selected)
