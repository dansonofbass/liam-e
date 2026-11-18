"""Typed calendar commands bind the owner-approved values and provider identity."""

from datetime import date
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from api.calendar.writes import LiveEvent, WriteRequest


class CalendarValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    start_local: str | None = None
    end_local: str | None = None
    timezone: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=8000)


def values(event: LiveEvent, zone: str) -> CalendarValues:
    return CalendarValues(title=event.title, start_date=event.start_date, end_date=event.end_date,
        start_local=event.start_at.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%dT%H:%M") if event.start_at else None,
        end_local=event.end_at.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%dT%H:%M") if event.end_at else None,
        timezone=zone if event.start_at else None, location=event.location, description=event.description)


class CalendarCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["create", "update", "delete"]
    source_id: str
    connection_ref: str = Field(exclude=True)
    occurrence_id: str | None = None
    expected_revision: str | None = None
    timezone: str
    before: LiveEvent | None = None
    after: CalendarValues | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler, info):
        result = handler(self)
        # Browser/SSE serialization defaults to redacted; persistence opts in explicitly.
        if info.context and info.context.get("storage"):
            result["connection_ref"] = self.connection_ref
        return result

    @model_validator(mode="after")
    def shape(self):
        if (self.action == "delete") != (self.after is None):
            raise ValueError("calendar_time_invalid")
        if self.action != "create" and (not self.occurrence_id or not self.expected_revision or self.before is None):
            raise ValueError("calendar_event_gone")
        return self

    def request(self, proposal_id: str) -> WriteRequest:
        payload = self.after.model_dump(exclude_none=True) if self.after else {}
        if self.action == "update":
            previous = values(self.before, self.timezone).model_dump()
            # Preserve unedited HTML and omitted provider fields by sending a true patch.
            payload = {k: v for k, v in payload.items() if previous.get(k) != v}
            time_fields = {"start_local", "end_local", "timezone", "start_date", "end_date"}
            if time_fields.intersection(payload):
                payload.update({k: v for k, v in self.after.model_dump(exclude_none=True).items() if k in time_fields})
        return WriteRequest(write_id=UUID(proposal_id), operation=self.action, source_id=self.source_id,
            occurrence_id=self.occurrence_id, expected_revision=self.expected_revision, **payload)
