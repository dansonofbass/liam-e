"""Concurrent durable job queue."""

import json
from datetime import datetime, timedelta

from sqlalchemy import and_, cast, delete, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert

from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.mail_job import MailJob


async def enqueue(kind: str, payload: dict, *, dedupe_key: str, run_after: datetime | None = None) -> MailJob | None:
    row = MailJob(kind=kind, payload_json=json.dumps(payload), dedupe_key=dedupe_key, run_after=run_after or utcnow())
    stmt = insert(MailJob).values(**row.model_dump()).on_conflict_do_nothing().returning(MailJob)
    async with get_session_maker()() as session:
        result = (await session.execute(stmt)).scalar_one_or_none()
        await session.commit()
        return result


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


async def finish(job_id: str) -> None:
    async with get_session_maker()() as session:
        row = await session.get(MailJob, job_id)
        if row is not None:
            row.status = "done"
            row.locked_at = None
            row.updated_at = utcnow()
            await session.commit()


async def fail(job_id: str, error_code: str, *, retry_at: datetime | None) -> None:
    async with get_session_maker()() as session:
        row = await session.get(MailJob, job_id)
        if row is not None:
            row.status = "queued" if retry_at is not None else "failed"
            if retry_at is not None:
                row.run_after = retry_at
            row.locked_at = None
            row.last_error = error_code
            row.updated_at = utcnow()
            await session.commit()


def _account(account_id: str):
    return cast(MailJob.payload_json, JSONB)["account_id"].astext == account_id


async def latest_for_account(account_id: str) -> MailJob | None:
    async with get_session_maker()() as session:
        return (await session.execute(select(MailJob).where(_account(account_id)).order_by(MailJob.created_at.desc(), MailJob.id.desc()).limit(1))).scalar_one_or_none()


async def delete_for_account(account_id: str) -> None:
    async with get_session_maker()() as session:
        await session.execute(delete(MailJob).where(_account(account_id)))
        await session.commit()
