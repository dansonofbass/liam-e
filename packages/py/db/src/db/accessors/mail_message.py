"""Accessor for ``mail_message`` rows: upsert during sync, search for the chat agent."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, or_, select, tuple_

from db.models.mail_insight import MailInsight

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
    sender_address: str = "",
    list_unsubscribe: str = "",
    list_unsubscribe_post: str = "",
    rfc_message_id: str = "",
    references: str = "",
    cc_json: str = "[]",
    attachments_json: str = "[]",
    is_flagged: bool = False,
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
        message.sender_address = sender_address.lower()
        message.list_unsubscribe = list_unsubscribe
        message.list_unsubscribe_post = list_unsubscribe_post
        message.rfc_message_id = rfc_message_id
        message.references = references
        message.cc_json = cc_json
        message.attachments_json = attachments_json
        message.is_flagged = is_flagged
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


@dataclass
class NewsletterRow:
    account_id: str
    sender_address: str
    sender_display: str
    total: int
    unread: int
    last_read_at: datetime | None
    list_unsubscribe: str
    list_unsubscribe_post: str
    labels_json: str


async def list_page(*, folder: str = "INBOX", account_ids: list[str] | None = None, unread_only: bool = False, important_only: bool = False, with_attachments: bool = False, query: str = "", before: tuple[datetime, str] | None = None, limit: int = 50) -> list[MailMessage]:
    date_key = func.coalesce(MailMessage.internal_date, datetime(1970, 1, 1, tzinfo=UTC))
    stmt = select(MailMessage).where(MailMessage.folder == folder)
    if account_ids is not None:
        stmt = stmt.where(MailMessage.account_id.in_(account_ids))
    if unread_only:
        stmt = stmt.where(MailMessage.is_read.is_(False))
    if important_only:
        stmt = stmt.where(or_(MailMessage.is_flagged.is_(True), exists(select(MailInsight.id).where(MailInsight.message_id == MailMessage.id, or_(MailInsight.deadline.is_not(None), MailInsight.needs_reply.is_(True))))))
    if with_attachments:
        stmt = stmt.where(MailMessage.has_attachments.is_(True))
    if query:
        stmt = stmt.where(MailMessage.search_tsv.op("@@")(func.websearch_to_tsquery("german", query)))
    if before is not None:
        stmt = stmt.where(tuple_(date_key, MailMessage.id) < tuple_(*before))
    stmt = stmt.order_by(date_key.desc(), MailMessage.id.desc()).limit(limit)
    async with get_session_maker()() as session:
        return list((await session.execute(stmt)).scalars().all())


async def count_unread(*, folder: str = "INBOX") -> dict[str, int]:
    async with get_session_maker()() as session:
        rows = await session.execute(select(MailMessage.account_id, func.count()).where(MailMessage.folder == folder, MailMessage.is_read.is_(False)).group_by(MailMessage.account_id))
        return dict(rows.all())


async def set_state(message_id: str, *, folder: str | None = None, is_read: bool | None = None, provider_uid: str | None = None, labels_json: str | None = None) -> MailMessage | None:
    async with get_session_maker()() as session:
        row = await session.get(MailMessage, message_id)
        if row is None:
            return None
        for name, value in (("folder", folder), ("is_read", is_read), ("provider_uid", provider_uid), ("labels_json", labels_json)):
            if value is not None:
                setattr(row, name, value)
        await session.commit()
        return row


async def newsletter_senders(*, account_ids: list[str] | None = None) -> list[NewsletterRow]:
    # Rank messages before aggregation so headers are taken from the newest message.
    stmt = select(MailMessage).where(MailMessage.folder == "INBOX", MailMessage.sender_address != "")
    if account_ids is not None:
        stmt = stmt.where(MailMessage.account_id.in_(account_ids))
    stmt = stmt.order_by(MailMessage.internal_date.desc().nullslast(), MailMessage.id.desc())
    async with get_session_maker()() as session:
        messages = (await session.execute(stmt)).scalars().all()
    grouped: dict[tuple[str, str], NewsletterRow] = {}
    for message in messages:
        key = (message.account_id, message.sender_address)
        if key not in grouped:
            grouped[key] = NewsletterRow(*key, message.sender, 0, 0, None, message.list_unsubscribe, message.list_unsubscribe_post, message.labels_json)
        row = grouped[key]
        row.total += 1
        row.unread += int(not message.is_read)
        if message.is_read and message.internal_date is not None and (row.last_read_at is None or message.internal_date > row.last_read_at):
            row.last_read_at = message.internal_date
    return list(grouped.values())


async def message_ids_from_sender(account_id: str, sender_address: str, *, folder: str = "INBOX") -> list[str]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(MailMessage.id).where(MailMessage.account_id == account_id, MailMessage.sender_address == sender_address.lower(), MailMessage.folder == folder))).scalars().all())


async def unread_without_insight(*, since: datetime, limit: int) -> list[MailMessage]:
    stmt = select(MailMessage).where(MailMessage.is_read.is_(False), MailMessage.internal_date >= since, ~exists(select(MailInsight.id).where(MailInsight.message_id == MailMessage.id))).order_by(MailMessage.internal_date.desc()).limit(limit)
    async with get_session_maker()() as session:
        return list((await session.execute(stmt)).scalars().all())


async def known_uids(account_id: str, folder: str) -> dict[str, str]:
    async with get_session_maker()() as session:
        return dict((await session.execute(select(MailMessage.provider_uid, MailMessage.id).where(MailMessage.account_id == account_id, MailMessage.folder == folder))).all())


async def delete_folder(account_id: str, folder: str) -> int:
    async with get_session_maker()() as session:
        result = await session.execute(delete(MailMessage).where(MailMessage.account_id == account_id, MailMessage.folder == folder))
        await session.commit()
        return result.rowcount


async def find_by_rfc_message_id(account_id: str, rfc_message_id: str) -> MailMessage | None:
    async with get_session_maker()() as session:
        return (await session.execute(select(MailMessage).where(MailMessage.account_id == account_id, MailMessage.rfc_message_id == rfc_message_id).limit(1))).scalar_one_or_none()
