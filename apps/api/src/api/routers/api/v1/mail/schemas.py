"""Response schemas for the indexed inbox."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from api.mail.actions import ActionKind


class AttachmentOut(BaseModel):
    name: str
    size: int
    content_type: str


class MessageListItemOut(BaseModel):
    id: str
    account_id: str
    color_index: int
    subject: str
    sender_name: str
    sender_address: str
    snippet: str
    internal_date: datetime | None
    is_read: bool
    is_flagged: bool
    has_attachments: bool
    deadline: date | None
    needs_reply: bool


class MessageDetailOut(MessageListItemOut):
    to: list[str]
    cc: list[str]
    body_text: str
    attachments: list[AttachmentOut]
    thread_id: str
    can_unsubscribe: bool


class MessagePageOut(BaseModel):
    items: list[MessageListItemOut]
    next_cursor: str | None


class MessageActionIn(BaseModel):
    kind: ActionKind


class MessageActionOut(BaseModel):
    action_id: str
    message: MessageListItemOut


class UndoIn(BaseModel):
    action_ids: list[str] = Field(min_length=1, max_length=200)


class UndoOut(BaseModel):
    restored: list[str]
    expired: list[str]
    skipped: list[str]
    failed: list[str]
