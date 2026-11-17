"""Short-lived encrypted configuration, consumed in the subscription transaction."""

from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from db.models._common import utc_datetime_column


class CalendarFeedValidation(SQLModel, table=True):
    __tablename__ = "calendar_feed_validation"

    token_digest: str = Field(primary_key=True)
    context_id: str
    config_digest: str
    encrypted_payload: str = Field(repr=False, sa_column=Column(Text, nullable=False))
    expires_at: datetime = Field(sa_column=utc_datetime_column(nullable=False, index=True))
