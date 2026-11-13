"""An undoable action and its previous message state."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class MailAction(SQLModel, table=True):
    __tablename__ = "mail_action"

    id: str = Field(default_factory=new_id, primary_key=True)
    message_id: str = Field(index=True)
    account_id: str
    kind: str
    previous_json: str
    created_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
    undone_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
