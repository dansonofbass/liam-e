"""Durable sync and insight jobs with open-job deduplication."""

from datetime import datetime

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow


class MailJob(SQLModel, table=True):
    __tablename__ = "mail_job"
    __table_args__ = (
        Index("uq_mail_job_open_dedupe", "dedupe_key", unique=True, postgresql_where=text("status IN ('queued', 'running')")),
        Index("ix_mail_job_status_run_after", "status", "run_after"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str
    payload_json: str
    dedupe_key: str
    status: str = "queued"
    attempts: int = 0
    run_after: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
    locked_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    last_error: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
