"""The synced message index: search across all accounts, read one message in full."""

import json
from datetime import datetime
from typing import Annotated

from db.accessors import mail_message as message_access
from db.models.mail_message import MailMessage
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class MessageOut(BaseModel):
    id: str
    account_id: str
    folder: str
    provider_uid: str
    thread_id: str
    subject: str
    sender: str
    recipients: list[str]
    snippet: str
    body_text: str
    internal_date: datetime | None
    has_attachments: bool
    is_read: bool
    labels: list[str]

    @classmethod
    def from_model(cls, message: MailMessage) -> "MessageOut":
        return cls(
            id=message.id,
            account_id=message.account_id,
            folder=message.folder,
            provider_uid=message.provider_uid,
            thread_id=message.thread_id,
            subject=message.subject,
            sender=message.sender,
            recipients=json.loads(message.recipients_json),
            snippet=message.snippet,
            body_text=message.body_text,
            internal_date=message.internal_date,
            has_attachments=message.has_attachments,
            is_read=message.is_read,
            labels=json.loads(message.labels_json),
        )


@router.get(
    "",
    operation_id="mail_messages_search",
    summary="Search the synced mail index across all accounts",
)
async def search_messages(
    q: Annotated[
        str, Query(description="Volltext über Betreff, Absender und Inhalt")
    ] = "",
    account_id: Annotated[str, Query()] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MessageOut]:
    messages = await message_access.search_messages(
        query=q, account_id=account_id, limit=limit
    )
    return [MessageOut.from_model(m) for m in messages]


@router.get(
    "/{message_id}",
    operation_id="mail_message_get",
    summary="Read one synced message in full",
)
async def get_message(message_id: str) -> MessageOut:
    message = await message_access.get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Mail nicht gefunden.")
    return MessageOut.from_model(message)
