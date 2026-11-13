"""The encrypted credential of one mail account.

``kind`` is ``oauth2_tokens`` (the token JSON of a Google/Microsoft account) or ``imap_password``
(IMAP/SMTP host settings plus the app password). ``encrypted_payload`` is a Fernet token produced
by ``api.mail.crypto``; the plaintext never reaches this table.
"""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class MailCredential(SQLModel, table=True):
    __tablename__ = "mail_credential"
    __table_args__ = (
        UniqueConstraint("account_id", "kind", name="uq_mail_credential_account_kind"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    account_id: str = Field(index=True)
    kind: str
    encrypted_payload: str
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=utc_datetime_column()
    )
