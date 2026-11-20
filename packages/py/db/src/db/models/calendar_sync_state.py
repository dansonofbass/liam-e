"""Persistent calendar coverage and last successful refresh."""

from datetime import datetime

from sqlalchemy import Boolean, Column, Integer, Text, text
from sqlmodel import Field, SQLModel

from db.models._common import utc_datetime_column


_ACCESS_PROOF = {
    "name": "guard_calendar_access",
    "function": "liam_calendar_access_proof",
    "events": "BEFORE INSERT OR UPDATE",
    "body": """BEGIN
    IF NEW.last_error IN ('address_check', 'reconnect_required', 'calendar_unavailable') THEN
        NEW.access_blocked := true;
    ELSIF TG_OP = 'UPDATE' THEN
        IF NEW.last_validated_at IS DISTINCT FROM OLD.last_validated_at
           AND NEW.last_validated_at = NEW.last_success_at AND NOT NEW.incomplete THEN
            NEW.access_blocked := false;
        ELSE
            NEW.access_blocked := OLD.access_blocked
                OR (OLD.last_success_at IS NOT NULL AND NOT OLD.incomplete AND NEW.incomplete);
        END IF;
    END IF;
    RETURN NEW;
END;""",
}

# A legacy scheduler may already have cleared the error when queuing a retry.
# Initialize the new column from the last validation before installing the trigger.
_INITIAL_ACCESS = """UPDATE calendar_sync_state AS s SET access_blocked = true
FROM calendar_source AS c
WHERE s.source_id = c.id AND c.provider IN ('google', 'ics') AND (
    s.last_error IN ('reconnect_required', 'calendar_unavailable', 'address_check')
    OR (s.last_success_at IS NOT NULL AND
        (s.last_checked_at > COALESCE(s.last_validated_at, s.last_success_at) OR s.incomplete)))"""


class CalendarSyncState(SQLModel, table=True):
    __tablename__ = "calendar_sync_state"
    __table_args__ = {"info": {"row_trigger": _ACCESS_PROOF}}

    source_id: str = Field(primary_key=True)
    coverage_start: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    coverage_end: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_success_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    incomplete: bool = True
    last_checked_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_validated_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    next_attempt_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_error: str | None = None
    # Maintained with provider proof in PostgreSQL, including updates from older workers.
    access_blocked: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false"),
        info={"initialize_existing": _INITIAL_ACCESS}))
    failure_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    data_revision: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    encrypted_validators: str | None = Field(default=None, repr=False, sa_column=Column(Text, nullable=True))
