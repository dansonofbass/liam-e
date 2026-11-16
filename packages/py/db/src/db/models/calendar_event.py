"""Provider-scoped calendar master and recurrence metadata."""

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id


class CalendarEvent(SQLModel, table=True):
    __tablename__ = "calendar_event"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_calendar_event_external"),
        Index("ix_calendar_event_source", "source_id"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    source_id: str
    external_id: str
    title: str = ""
    recurrence_json: str = "{}"
