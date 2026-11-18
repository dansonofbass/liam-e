"""Private ICS address storage; never serialize this table into public responses."""

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class CalendarFeedConfig(SQLModel, table=True):
    __tablename__ = "calendar_feed_config"

    source_id: str = Field(primary_key=True)
    encrypted_payload: str = Field(repr=False, sa_column=Column(Text, nullable=False))
