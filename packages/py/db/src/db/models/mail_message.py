"""One synced mail message of one account — the searchable index the chat agent works on.

``provider_uid`` is the provider's own id (Gmail message id, IMAP UID per folder, Graph id), unique
per (account, folder). ``body_text`` is capped at ``MAIL_SYNC_MAX_BODY_CHARS`` during sync so one
huge mail cannot dominate the index. ``recipients_json``/``labels_json`` are JSON arrays of strings.
``folder`` is normalized to INBOX, ARCHIVE, TRASH, or another MAIL_SYNC_FOLDERS folder.
"""

from datetime import datetime

from sqlalchemy import Column, Computed, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class MailMessage(SQLModel, table=True):
    __tablename__ = "mail_message"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "folder",
            "provider_uid",
            name="uq_mail_message_account_folder_uid",
        ),
        Index("ix_mail_message_account_date", "account_id", "internal_date"),
        Index("ix_mail_message_folder_date", "folder", "internal_date", "id"),
        Index("ix_mail_message_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    account_id: str = Field(index=True)
    folder: str = "INBOX"
    provider_uid: str
    thread_id: str = ""
    subject: str = ""
    sender: str = ""
    sender_address: str = Field(default="", index=True)
    list_unsubscribe: str = ""
    list_unsubscribe_post: str = ""
    rfc_message_id: str = ""
    references: str = ""
    cc_json: str = "[]"
    attachments_json: str = "[]"
    is_flagged: bool = False
    search_tsv: str | None = Field(default=None, sa_column=Column(TSVECTOR, Computed("to_tsvector('german', coalesce(subject,'') || ' ' || coalesce(sender,'') || ' ' || coalesce(body_text,''))", persisted=True)))
    recipients_json: str = "[]"
    snippet: str = ""
    body_text: str = ""
    internal_date: datetime | None = Field(
        default=None, sa_column=utc_datetime_column(nullable=True)
    )
    has_attachments: bool = False
    is_read: bool = False
    labels_json: str = "[]"
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
