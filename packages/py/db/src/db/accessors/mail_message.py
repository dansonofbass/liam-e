"""Accessor for ``mail_message`` rows: upsert during sync, search for the chat agent."""

import json
from collections.abc import Collection
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, or_, select, tuple_
from sqlmodel.ext.asyncio.session import AsyncSession

from db.models.mail_insight import MailInsight

from db.engine import get_session_maker
from db.models.mail_message import MailMessage


@asynccontextmanager
async def _writer(session):
    if session is None:
        async with get_session_maker().begin() as owned:
            yield owned
    else:
        yield session


def _connector_labels(stored: str, *, folder: str | None = None, is_read: bool | None = None, is_flagged: bool | None = None) -> str:
    try:
        labels = json.loads(stored)
    except (TypeError, ValueError):
        labels = []
    labels = [label for label in labels if isinstance(label, str)] if isinstance(labels, list) else []
    for label, present in (("INBOX", folder == "INBOX" if folder is not None else None),
                           ("UNREAD", not is_read if is_read is not None else None), ("STARRED", is_flagged)):
        if present and label not in labels:
            labels.append(label)
        elif present is False:
            labels = [value for value in labels if value != label]
    return json.dumps(labels)


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
    is_read: bool | None = False,
    labels_json: str | None = "[]",
    sender_address: str = "",
    list_unsubscribe: str = "",
    list_unsubscribe_post: str = "",
    rfc_message_id: str = "",
    references: str = "",
    cc_json: str = "[]",
    reply_to_json: str = "[]",
    attachments_json: str = "[]",
    is_flagged: bool | None = False,
    body_version: int = 0,
    drop_insight: bool = False,
    unverified_connector: bool = False,
    session: AsyncSession | None = None,
    invalidated_insights: list[str] | None = None,
) -> MailMessage:
    """Insert the message, or refresh it when (account, folder, uid) already exists. `drop_insight`
    removes its insight in the same transaction (the summarized text changed)."""
    async with _writer(session) as session:
        result = await session.execute(
            select(MailMessage).where(
                MailMessage.account_id == account_id,
                MailMessage.folder == folder,
                MailMessage.provider_uid == provider_uid,
            ).with_for_update()
        )
        message = result.scalar_one_or_none()
        new = message is None
        if message is None:
            message = MailMessage(
                account_id=account_id, folder=folder, provider_uid=provider_uid
            )
        reverified = message.unverified_connector and not unverified_connector
        drop_insight = drop_insight or reverified
        message.unverified_connector = unverified_connector
        message.thread_id = thread_id
        message.subject = subject
        message.sender = sender
        message.sender_address = sender_address.lower()
        message.list_unsubscribe = list_unsubscribe
        message.list_unsubscribe_post = list_unsubscribe_post
        message.rfc_message_id = rfc_message_id
        message.references = references
        message.cc_json = cc_json
        message.reply_to_json = reply_to_json
        message.attachments_json = attachments_json
        # A connector can prove inbox membership without returning its flags. Preserve
        # trusted flags on an existing row, and never carry unverified labels into chat.
        if is_flagged is not None or new or reverified:
            message.is_flagged = is_flagged if is_flagged is not None else False
        message.recipients_json = recipients_json
        message.snippet = snippet
        message.body_text = body_text
        message.body_version = body_version
        message.internal_date = internal_date
        message.has_attachments = has_attachments
        if is_read is not None or new or reverified:
            message.is_read = is_read if is_read is not None else True
        message.labels_json = (labels_json if labels_json is not None else
            _connector_labels("[]" if new or reverified else message.labels_json,
                              folder=folder, is_read=is_read, is_flagged=is_flagged))
        session.add(message)
        if drop_insight and message.id:
            removed = await _drop_insight(session, message.id)
            if (removed or reverified) and not message.is_read and invalidated_insights is not None:
                invalidated_insights.append(message.id)
        return message


async def search_messages(
    *, query: str = "", account_id: str = "", limit: int = 50
) -> list[MailMessage]:
    """Case-insensitive substring search over subject, sender, and body across accounts."""
    stmt = select(MailMessage).where(MailMessage.folder != "SPAM")
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


async def get_message(message_id: str, session: AsyncSession | None = None) -> MailMessage | None:
    if session is not None:
        return await session.get(MailMessage, message_id)
    async with get_session_maker()() as session:
        return await session.get(MailMessage, message_id)


async def get_scoped_message(message_id: str, account_ids: list[str], *, folder: str) -> MailMessage | None:
    """Read a single indexed row of one folder without probing outside the authorized scope."""
    stmt = select(MailMessage).where(
        MailMessage.id == message_id, MailMessage.account_id.in_(account_ids), MailMessage.folder == folder
    )
    async with get_session_maker()() as session:
        return (await session.execute(stmt)).scalar_one_or_none()


async def inbox_counts(account_ids: list[str]) -> dict[str, tuple[int, int]]:
    """Count stored inbox rows and unread rows, restricted in the query itself."""
    stmt = (select(MailMessage.account_id, func.count(), func.count().filter(MailMessage.is_read.is_(False)))
            .where(MailMessage.folder == "INBOX", MailMessage.account_id.in_(account_ids))
            .group_by(MailMessage.account_id))
    async with get_session_maker()() as session:
        return {account_id: (total, unread) for account_id, total, unread in (await session.execute(stmt)).all()}


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


async def list_page(*, chat_only: bool = False, folder: str = "INBOX", account_ids: list[str] | None = None, unread_only: bool = False, important_only: bool = False, with_attachments: bool = False, query: str = "", before: tuple[datetime | None, str] | None = None, limit: int = 50) -> list[MailMessage]:
    date_key = func.coalesce(MailMessage.internal_date, datetime(1970, 1, 1, tzinfo=UTC))
    stmt = select(MailMessage).where(MailMessage.folder == folder)
    if account_ids is not None:
        stmt = stmt.where(MailMessage.account_id.in_(account_ids))
    if chat_only:
        stmt = stmt.where(MailMessage.unverified_connector.is_(False))
    if unread_only:
        stmt = stmt.where(MailMessage.is_read.is_(False))
    if important_only:
        stmt = stmt.where(or_(MailMessage.is_flagged.is_(True), exists(select(MailInsight.id).where(MailInsight.message_id == MailMessage.id, or_(MailInsight.deadline.is_not(None), MailInsight.needs_reply.is_(True))))))
    if with_attachments:
        stmt = stmt.where(MailMessage.has_attachments.is_(True))
    if query:
        stmt = stmt.where(MailMessage.search_tsv.op("@@")(func.websearch_to_tsquery("german", query)))
    if before is not None:
        stmt = stmt.where(tuple_(date_key, MailMessage.id) < tuple_(before[0] or datetime(1970, 1, 1, tzinfo=UTC), before[1]))
    stmt = stmt.order_by(date_key.desc(), MailMessage.id.desc()).limit(limit)
    async with get_session_maker()() as session:
        return list((await session.execute(stmt)).scalars().all())


async def count_unread(*, chat_only: bool = False, folder: str = "INBOX", account_ids: list[str] | None = None) -> dict[str, int]:
    async with get_session_maker()() as session:
        query = select(MailMessage.account_id, func.count()).where(MailMessage.folder == folder, MailMessage.is_read.is_(False))
        if account_ids is not None:
            query = query.where(MailMessage.account_id.in_(account_ids))
        if chat_only:
            query = query.where(MailMessage.unverified_connector.is_(False))
        rows = await session.execute(query.group_by(MailMessage.account_id))
        return dict(rows.all())


async def set_state(message_id: str, *, session: AsyncSession | None = None, folder: str | None = None, is_read: bool | None = None, is_flagged: bool | None = None, provider_uid: str | None = None, labels_json: str | None = None, connector_labels: bool = False) -> MailMessage | None:
    async with _writer(session) as session:
        row = await session.get(MailMessage, message_id)
        if row is None:
            return None
        if connector_labels and labels_json is None:
            labels_json = _connector_labels(row.labels_json, folder=folder, is_read=is_read, is_flagged=is_flagged)
        for name, value in (("folder", folder), ("is_read", is_read), ("is_flagged", is_flagged), ("provider_uid", provider_uid), ("labels_json", labels_json)):
            if value is not None:
                setattr(row, name, value)
        return row


async def delete_duplicate(account_id: str, folder: str, provider_uid: str, *, keep_id: str, rfc_message_id: str) -> bool:
    """Remove only a sync copy of the same identified message, never another mail."""
    if not rfc_message_id:
        return False
    async with get_session_maker()() as session:
        result = await session.execute(delete(MailMessage).where(
            MailMessage.account_id == account_id,
            MailMessage.folder == folder,
            MailMessage.provider_uid == provider_uid,
            MailMessage.id != keep_id,
            MailMessage.rfc_message_id == rfc_message_id,
        ))
        await session.commit()
        return bool(result.rowcount)


async def newsletter_senders(*, chat_only: bool = False, account_ids: list[str] | None = None) -> list[NewsletterRow]:
    partition = (MailMessage.account_id, MailMessage.sender_address)
    date_key = func.coalesce(MailMessage.internal_date, datetime(1970, 1, 1, tzinfo=UTC))
    ranked = select(
        MailMessage.account_id, MailMessage.sender_address, MailMessage.sender,
        func.count().over(partition_by=partition).label("total"),
        func.count().filter(MailMessage.is_read.is_(False)).over(partition_by=partition).label("unread"),
        func.max(MailMessage.internal_date).filter(MailMessage.is_read.is_(True)).over(partition_by=partition).label("last_read_at"),
        MailMessage.list_unsubscribe, MailMessage.list_unsubscribe_post, MailMessage.labels_json,
        func.row_number().over(partition_by=partition, order_by=(date_key.desc(), MailMessage.id.desc())).label("rank"),
    ).where(MailMessage.folder == "INBOX", MailMessage.sender_address != "")
    if account_ids is not None:
        ranked = ranked.where(MailMessage.account_id.in_(account_ids))
    if chat_only:
        ranked = ranked.where(MailMessage.unverified_connector.is_(False))
    ranked = ranked.subquery()
    stmt = select(ranked.c.account_id, ranked.c.sender_address, ranked.c.sender, ranked.c.total, ranked.c.unread, ranked.c.last_read_at, ranked.c.list_unsubscribe, ranked.c.list_unsubscribe_post, ranked.c.labels_json).where(ranked.c.rank == 1).order_by(ranked.c.total.desc(), ranked.c.sender_address, ranked.c.account_id)
    async with get_session_maker()() as session:
        return [NewsletterRow(*row) for row in (await session.execute(stmt)).all()]


async def message_ids_from_sender(account_id: str, sender_address: str, *, folder: str = "INBOX") -> list[str]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(MailMessage.id).where(MailMessage.account_id == account_id, MailMessage.sender_address == sender_address.lower(), MailMessage.folder == folder, MailMessage.unverified_connector.is_(False)))).scalars().all())


async def unread_without_insight(*, since: datetime, limit: int, exclude_account_ids: Collection[str] = (),
                                 account_id: str | None = None, verified_ids: Collection[str] | None = None) -> list[MailMessage]:
    stmt = select(MailMessage).where(MailMessage.folder != "SPAM", MailMessage.is_read.is_(False), MailMessage.internal_date >= since, ~exists(select(MailInsight.id).where(MailInsight.message_id == MailMessage.id)))
    if account_id is not None:
        stmt = stmt.where(MailMessage.account_id == account_id)
    if verified_ids is not None:
        stmt = stmt.where(MailMessage.id.in_(verified_ids), MailMessage.unverified_connector.is_(False))
    if exclude_account_ids:
        stmt = stmt.where(MailMessage.account_id.not_in(list(exclude_account_ids)))
    stmt = stmt.order_by(MailMessage.internal_date.desc()).limit(limit)
    async with get_session_maker()() as session:
        return list((await session.execute(stmt)).scalars().all())


async def known_uids(account_id: str, folder: str, *, verified_only: bool = False, session: AsyncSession | None = None) -> dict[str, str]:
    query = select(MailMessage.provider_uid, MailMessage.id).where(MailMessage.account_id == account_id, MailMessage.folder == folder)
    if verified_only:
        query = query.where(MailMessage.unverified_connector.is_(False))
    async with (nullcontext(session) if session is not None else get_session_maker()()) as session:
        return dict((await session.execute(query)).all())


async def reconcile_connector_folders(session: AsyncSession, account_id: str, inbox: set[str], archived: set[str]) -> None:
    """The Studio provider UID follows a message between INBOX and ARCHIVE."""
    if not inbox and not archived:
        return
    rows = (await session.scalars(select(MailMessage).where(
        MailMessage.account_id == account_id, MailMessage.provider_uid.in_(inbox | archived),
        MailMessage.folder.in_(("INBOX", "ARCHIVE")),
    ).order_by(MailMessage.id).with_for_update())).all()
    by_uid: dict[str, dict[str, MailMessage]] = {}
    for row in rows:
        by_uid.setdefault(row.provider_uid, {})[row.folder] = row
    moves = []
    duplicate_ids = []
    for uid, copies in by_uid.items():
        target = "ARCHIVE" if uid in archived else "INBOX"
        active = copies.get("INBOX")
        stored = copies.get("ARCHIVE")
        if active is not None and stored is not None:
            # Retain the active inbox identity. An unverified copy cannot displace a
            # verified archive when the only new evidence is that the UID left the inbox.
            keep_archive = target == "ARCHIVE" and active.unverified_connector and not stored.unverified_connector
            keep, duplicate = (stored, active) if keep_archive else (active, stored)
            duplicate_ids.append(duplicate.id)
            await session.delete(duplicate)
        else:
            keep = next(iter(copies.values()))
        if keep.folder != target:
            moves.append((keep, target))
    if duplicate_ids:
        await session.execute(delete(MailInsight).where(MailInsight.message_id.in_(duplicate_ids)))
        await session.flush()
    for row, target in moves:
        row.folder = target
        row.labels_json = _connector_labels(row.labels_json, folder=target)
    await session.flush()


async def stale_body_texts(account_id: str, folder: str, version: int, uids: list[str], *, session: AsyncSession | None = None) -> dict[str, str]:
    """Stored text of the given rows whose body comes from an older text extraction, by provider id."""
    if not uids:
        return {}
    stmt = select(MailMessage.provider_uid, MailMessage.body_text).where(
        MailMessage.account_id == account_id, MailMessage.folder == folder, MailMessage.body_version < version, MailMessage.provider_uid.in_(uids))
    async with (nullcontext(session) if session is not None else get_session_maker()()) as session:
        return {uid: text for uid, text in (await session.execute(stmt)).all()}


async def stale_bodies(account_id: str, folder: str, version: int, *, limit: int, exclude: Collection[str] = ()) -> list[MailMessage]:
    """The newest rows whose body comes from an older text extraction, to re-read from the provider;
    `exclude` names rows that wait for a later try."""
    stmt = select(MailMessage).where(MailMessage.account_id == account_id, MailMessage.folder == folder, MailMessage.body_version < version)
    if exclude:
        stmt = stmt.where(MailMessage.id.not_in(list(exclude)))
    stmt = (stmt.order_by(MailMessage.internal_date.desc().nulls_last(), MailMessage.id).limit(limit))
    async with get_session_maker()() as session:
        return list((await session.execute(stmt)).scalars().all())


async def _drop_insight(session, message_id: str) -> bool:
    # The row is written first: its lock makes an insight being stored for the old text either land
    # before this delete or see the new text (mail_insight.store_if_missing, `summarized`).
    await session.flush()
    removed = await session.execute(delete(MailInsight).where(MailInsight.message_id == message_id))
    return bool(removed.rowcount)


async def set_body(message_id: str, *, session: AsyncSession | None = None, body_version: int, body_text: str | None = None, snippet: str | None = None, drop_insight: bool = False) -> None:
    """Store a re-read body; without text only the version moves on (the provider no longer has the mail).
    `drop_insight` removes its insight in the same transaction."""
    async with _writer(session) as session:
        row = await session.get(MailMessage, message_id)
        if row is None:
            return
        row.body_version = body_version
        if body_text is not None:
            row.body_text = body_text
        if snippet is not None:
            row.snippet = snippet
        if drop_insight:
            await _drop_insight(session, message_id)


async def delete_folder(account_id: str, folder: str) -> int:
    async with get_session_maker()() as session:
        result = await session.execute(delete(MailMessage).where(MailMessage.account_id == account_id, MailMessage.folder == folder))
        await session.commit()
        return result.rowcount


async def find_by_rfc_message_id(account_id: str, rfc_message_id: str) -> MailMessage | None:
    async with get_session_maker()() as session:
        return (await session.execute(select(MailMessage).where(MailMessage.account_id == account_id, MailMessage.rfc_message_id == rfc_message_id).limit(1))).scalar_one_or_none()
