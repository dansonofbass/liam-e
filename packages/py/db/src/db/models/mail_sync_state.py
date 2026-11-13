"""Sync progress of one mail account: where the last run stopped and how it ended.

``cursor`` is provider-specific (Gmail ``historyId``, IMAP UIDVALIDITY + last UID, Graph
``@odata.deltaLink``). One row per account.
"""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class MailSyncState(SQLModel, table=True):
    __tablename__ = "mail_sync_state"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_mail_sync_state_account"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    account_id: str = Field(index=True)
    cursor: str = ""
    status: str = "idle"  # idle | syncing | ok | error
    last_error: str = ""
    last_sync_at: datetime | None = Field(
        default=None, sa_column=utc_datetime_column(nullable=True)
    )
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
