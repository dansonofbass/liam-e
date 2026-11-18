"""Calendar source selection and provider connection reference."""

from sqlalchemy import Column, Index, Integer, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from db.models._common import new_id


class CalendarSource(SQLModel, table=True):
    __tablename__ = "calendar_source"
    __table_args__ = (
        UniqueConstraint("provider", "connection_ref", "external_id", name="uq_calendar_source_external"),
        Index("ix_calendar_source_active", "is_active"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    provider: str
    connection_ref: str
    external_id: str
    name: str
    timezone: str
    capabilities_json: str = "[]"
    is_active: bool = True
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
