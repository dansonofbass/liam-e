"""Public, deliberately narrow schemas for the indexed mail read surface."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IndexStatus(BaseModel):
    account_id: str
    last_sync_at: datetime | None
    incomplete: bool
    stale: bool = True
    warnings: list[str]


class Envelope(BaseModel):
    schema_version: Literal[1] = 1
    scope: list[str]
    index: list[IndexStatus]
    warnings: list[str] = Field(default_factory=lambda: ["inbox_index_only", "provider_freshness_unknown"])
    truncated: bool = False


class AccountItem(BaseModel):
    id: str
    display_name: str
    truncated: bool = False


class AccountsResult(Envelope):
    accounts: list[AccountItem]


class MessageItem(BaseModel):
    id: str
    account_id: str
    folder: str
    subject: str
    sender: str
    date: datetime | None
    snippet: str
    is_read: bool
    app_link: str
    truncated: bool = False


class SearchResult(Envelope):
    untrusted_messages: list[MessageItem]
    next_cursor: str | None = None


class ReadResult(Envelope):
    untrusted_message: MessageItem
    body_text: str
    body_available: bool


class AccountCount(BaseModel):
    account_id: str
    total: int
    unread: int


class SummaryResult(Envelope):
    counts: list[AccountCount]
    total: int
    unread: int
