"""Concurrent durable job queue."""

import json
from datetime import datetime, timedelta

from sqlalchemy import and_, cast, delete, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert

from db.engine import get_session_maker
from db.models._common import new_id, utcnow
from db.models.mail_job import MailJob


async def enqueue(kind: str, payload: dict, *, dedupe_key: str, run_after: datetime | None = None) -> MailJob | None:
    row = MailJob(kind=kind, payload_json=json.dumps(payload), dedupe_key=dedupe_key, run_after=run_after or utcnow())
    stmt = insert(MailJob).values(**row.model_dump()).on_conflict_do_nothing().returning(MailJob)
    async with get_session_maker()() as session:
        result = (await session.execute(stmt)).scalar_one_or_none()
        await session.commit()
        return result


def queue_verified_insights(session, account_id: str, message_ids: list[str], limit: int) -> None:
    """Commit bounded refresh jobs with the verified mail batch that invalidated its insights."""
    if limit <= 0:
        return
    for offset in range(0, len(message_ids), limit):
        payload = {"account_id": account_id, "message_ids": message_ids[offset:offset + limit]}
        # Each invalidation is durable even while an earlier job for the same mail is running.
        session.add(MailJob(kind="insights", payload_json=json.dumps(payload), dedupe_key=f"insights-refresh:{new_id()}"))


async def claim_next(now: datetime, *, stale_after: timedelta) -> MailJob | None:
    stmt = select(MailJob).where(or_(and_(MailJob.status == "queued", MailJob.run_after <= now), and_(MailJob.status == "running", MailJob.locked_at < now - stale_after))).order_by(MailJob.run_after, MailJob.id).with_for_update(skip_locked=True).limit(1)
    async with get_session_maker()() as session:
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            row.status = "running"
            row.locked_at = now
            row.attempts += 1
            row.updated_at = now
            await session.commit()
        return row


async def finish(job_id: str, attempt: int) -> bool:
    stmt = (update(MailJob).where(MailJob.id == job_id, MailJob.status == "running", MailJob.attempts == attempt)
            .values(status="done", locked_at=None, updated_at=utcnow()).returning(MailJob.id))
    async with get_session_maker()() as session:
        applied = (await session.execute(stmt)).scalar_one_or_none() is not None
        await session.commit()
        return applied


async def fail(job_id: str, attempt: int, error_code: str, *, retry_at: datetime | None) -> bool:
    values = dict(status="queued" if retry_at is not None else "failed", locked_at=None,
                  last_error=error_code, updated_at=utcnow())
    if retry_at is not None:
        values["run_after"] = retry_at
    stmt = (update(MailJob).where(MailJob.id == job_id, MailJob.status == "running", MailJob.attempts == attempt)
            .values(**values).returning(MailJob.id))
    async with get_session_maker()() as session:
        applied = (await session.execute(stmt)).scalar_one_or_none() is not None
        await session.commit()
        return applied


def _account(account_id: str):
    return cast(MailJob.payload_json, JSONB)["account_id"].astext == account_id


async def latest_for_account(account_id: str, *, kind: str | None = None, open_only: bool = False) -> MailJob | None:
    stmt = select(MailJob).where(_account(account_id))
    if kind is not None:
        stmt = stmt.where(MailJob.kind == kind)
    if open_only:
        stmt = stmt.where(MailJob.status.in_(("queued", "running")))
    async with get_session_maker()() as session:
        return (await session.execute(stmt.order_by(MailJob.created_at.desc(), MailJob.id.desc()).limit(1))).scalar_one_or_none()


async def delete_for_account(account_id: str) -> None:
    async with get_session_maker()() as session:
        await session.execute(delete(MailJob).where(_account(account_id)))
        await session.commit()
