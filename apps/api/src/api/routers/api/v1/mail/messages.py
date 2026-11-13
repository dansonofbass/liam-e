"""The synced message index: page through messages and read one in full."""

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from db.accessors import mail_account as account_access
from db.accessors import mail_insight as insight_access
from db.accessors import mail_message as message_access
from db.models.mail_insight import MailInsight
from db.models.mail_message import MailMessage
from fastapi import APIRouter, HTTPException, Query

from api.errors import refuse
from api.mail.headers import sender_name
from api.mail.state import color_indexes
from api.routers.api.v1.mail.schemas import MessageDetailOut, MessageListItemOut, MessagePageOut

router = APIRouter()
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def encode_cursor(message: MailMessage) -> str:
    key = f"{(message.internal_date or EPOCH).isoformat()}|{message.id}"
    return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode()
        date_text, message_id = raw.split("|")
        dt = datetime.fromisoformat(date_text)
        if not message_id or dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("Invalid cursor key")
        return dt, message_id
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise refuse(422, "cursor_invalid", "Diese Seite konnte nicht geladen werden. Öffne den Posteingang noch einmal.") from error


def list_item(message: MailMessage, colors: dict[str, int], insight: MailInsight | None) -> MessageListItemOut:
    return MessageListItemOut(
        id=message.id, account_id=message.account_id,
        color_index=colors.get(message.account_id, 0), subject=message.subject,
        sender_name=sender_name(message.sender), sender_address=message.sender_address,
        snippet=message.snippet, internal_date=message.internal_date,
        is_read=message.is_read, is_flagged=message.is_flagged,
        has_attachments=message.has_attachments,
        deadline=insight.deadline if insight else None,
        needs_reply=insight.needs_reply if insight else False,
    )


@router.get("", operation_id="mail_messages_list", summary="List the synced inbox")
async def list_messages(
    cursor: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    account_id: Annotated[list[str], Query()] = [],
    unread: bool = False,
    important: bool = False,
    attachments: bool = False,
    q: str = "",
    folder: Literal["INBOX", "ARCHIVE", "TRASH"] = "INBOX",
) -> MessagePageOut:
    """List messages with filters and an opaque cursor for the next page."""
    before = decode_cursor(cursor) if cursor else None
    messages = await message_access.list_page(
        folder=folder, account_ids=account_id or None, unread_only=unread,
        important_only=important, with_attachments=attachments, query=q,
        before=before, limit=limit,
    )
    insights = await insight_access.get_for_messages([message.id for message in messages])
    colors = color_indexes(await account_access.list_accounts())
    return MessagePageOut(
        items=[list_item(message, colors, insights.get(message.id)) for message in messages],
        next_cursor=encode_cursor(messages[-1]) if len(messages) == limit else None,
    )


@router.get("/{message_id}", operation_id="mail_message_get", summary="Read one synced message in full")
async def get_message(message_id: str) -> MessageDetailOut:
    """Return one indexed message or 404 if it does not exist."""
    message = await message_access.get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Mail nicht gefunden.")
    insights = await insight_access.get_for_messages([message.id])
    colors = color_indexes(await account_access.list_accounts())
    return MessageDetailOut(
        **list_item(message, colors, insights.get(message.id)).model_dump(),
        to=json.loads(message.recipients_json), cc=json.loads(message.cc_json),
        body_text=message.body_text, attachments=json.loads(message.attachments_json),
        thread_id=message.thread_id, can_unsubscribe=bool(message.list_unsubscribe),
    )
