"""Accessor for ``mail_message`` rows: upsert during sync, search for the chat agent."""

from datetime import datetime

from sqlalchemy import or_, select

from db.engine import get_session_maker
from db.models.mail_message import MailMessage


async def upsert_message(
    *,
    account_id: str,
    folder: str,
    provider_uid: str,
    thread_id: str = "",
    subject: str = "",
    sender: str = "",
    recipients_json: str = "[]",
    snippet: str = "",
    body_text: str = "",
    internal_date: datetime | None = None,
    has_attachments: bool = False,
    is_read: bool = False,
    labels_json: str = "[]",
) -> MailMessage:
    """Insert the message, or refresh it when (account, folder, uid) already exists."""
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailMessage).where(
                MailMessage.account_id == account_id,
                MailMessage.folder == folder,
                MailMessage.provider_uid == provider_uid,
            )
        )
        message = result.scalar_one_or_none()
        if message is None:
            message = MailMessage(
                account_id=account_id, folder=folder, provider_uid=provider_uid
            )
        message.thread_id = thread_id
        message.subject = subject
        message.sender = sender
        message.recipients_json = recipients_json
        message.snippet = snippet
        message.body_text = body_text
        message.internal_date = internal_date
        message.has_attachments = has_attachments
        message.is_read = is_read
        message.labels_json = labels_json
        session.add(message)
        await session.commit()
        return message


async def search_messages(
    *, query: str = "", account_id: str = "", limit: int = 50
) -> list[MailMessage]:
    """Case-insensitive substring search over subject, sender, and body across accounts."""
    stmt = select(MailMessage)
    if account_id:
        stmt = stmt.where(MailMessage.account_id == account_id)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            or_(
                MailMessage.subject.ilike(pattern),
                MailMessage.sender.ilike(pattern),
                MailMessage.body_text.ilike(pattern),
            )
        )
    stmt = stmt.order_by(MailMessage.internal_date.desc().nullslast()).limit(limit)
    async with get_session_maker()() as session:
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_message(message_id: str) -> MailMessage | None:
    async with get_session_maker()() as session:
        return await session.get(MailMessage, message_id)


async def count_for_account(account_id: str) -> int:
    from sqlalchemy import func

    async with get_session_maker()() as session:
        result = await session.execute(
            select(func.count())
            .select_from(MailMessage)
            .where(MailMessage.account_id == account_id)
        )
        return int(result.scalar_one())


async def delete_for_account(account_id: str) -> None:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailMessage).where(MailMessage.account_id == account_id)
        )
        for message in result.scalars().all():
            await session.delete(message)
        await session.commit()
