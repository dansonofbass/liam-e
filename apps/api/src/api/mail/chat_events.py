"""Typed events emitted during a chat turn."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from api.mail.chat_schemas import ChatMessageOut, CalendarRefOut


class EventModel(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class StartEvent(EventModel):
    event: Literal['start'] = 'start'
    conversation_id: str
    user_message_id: str
    model: str


class StatusEvent(EventModel):
    event: Literal['status'] = 'status'
    code: Literal['thinking', 'searching', 'reading', 'checking_deadlines', 'finding_newsletters', 'preparing_proposal']
    count: int | None = None


class DeltaEvent(EventModel):
    event: Literal['delta'] = 'delta'
    text: str


class MailRefOut(EventModel):
    id: str
    account_id: str
    color_index: int
    subject: str
    sender_name: str
    snippet: str
    internal_date: datetime | None
    deadline: date | None
    is_flagged: bool


class MailsEvent(EventModel):
    event: Literal['mails'] = 'mails'
    mails: list[MailRefOut]


class CalendarsEvent(EventModel):
    event: Literal['calendars'] = 'calendars'
    calendars: list[CalendarRefOut]


class ProposalEvent(EventModel):
    event: Literal['proposal'] = 'proposal'
    message: ChatMessageOut


class SuggestionsEvent(EventModel):
    event: Literal['suggestions'] = 'suggestions'
    items: list[str] = Field(max_length=3)


class DoneEvent(EventModel):
    event: Literal['done'] = 'done'
    conversation_id: str
    message_id: str
    stopped: bool


class ErrorEvent(EventModel):
    event: Literal['error'] = 'error'
    code: Literal['model_unavailable', 'aborted', 'internal', 'context_revoked', 'calendar_reference_unavailable', 'preferences_unavailable']


ChatEvent = Annotated[StartEvent | StatusEvent | DeltaEvent | MailsEvent | CalendarsEvent | ProposalEvent | SuggestionsEvent | DoneEvent | ErrorEvent, Field(discriminator='event')]
