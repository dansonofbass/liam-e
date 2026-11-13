"""Typed events emitted during a chat turn."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from api.mail.chat_schemas import ChatMessageOut


class StartEvent(BaseModel):
    event: Literal['start'] = 'start'
    conversation_id: str
    user_message_id: str


class StatusEvent(BaseModel):
    event: Literal['status'] = 'status'
    code: Literal['thinking', 'searching', 'reading', 'checking_deadlines', 'finding_newsletters', 'preparing_proposal']
    count: int | None = None


class DeltaEvent(BaseModel):
    event: Literal['delta'] = 'delta'
    text: str


class MailRefOut(BaseModel):
    id: str
    account_id: str
    color_index: int
    subject: str
    sender_name: str
    internal_date: datetime | None
    deadline: date | None


class MailsEvent(BaseModel):
    event: Literal['mails'] = 'mails'
    mails: list[MailRefOut]


class ProposalEvent(BaseModel):
    event: Literal['proposal'] = 'proposal'
    message: ChatMessageOut


class SuggestionsEvent(BaseModel):
    event: Literal['suggestions'] = 'suggestions'
    items: list[str] = Field(max_length=3)


class DoneEvent(BaseModel):
    event: Literal['done'] = 'done'
    conversation_id: str
    message_id: str
    stopped: bool


class ErrorEvent(BaseModel):
    event: Literal['error'] = 'error'
    code: Literal['model_unavailable', 'aborted', 'internal']


ChatEvent = Annotated[StartEvent | StatusEvent | DeltaEvent | MailsEvent | ProposalEvent | SuggestionsEvent | DoneEvent | ErrorEvent, Field(discriminator='event')]
