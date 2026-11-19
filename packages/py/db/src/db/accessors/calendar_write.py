"""Short transactions for claims and outcomes; never retry provider writes."""

from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from db.accessors._calendar_lock import lock_source
from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.calendar_source import CalendarSource
from db.models.calendar_write import CalendarWrite


ABANDONED_REQUEST_HASH = "abandoned"


class WriteConflict(Exception):
    pass


class WriteInProgress(Exception):
    pass


async def claim(row: CalendarWrite) -> tuple[CalendarWrite, bool]:
    async with get_session_maker()() as session:
        await lock_source(session, row.source_id)
        existing = await session.get(CalendarWrite, row.id)
        if existing is not None:
            if existing.request_hash != row.request_hash:
                raise WriteConflict()
            return existing, False
        inserted = (await session.execute(insert(CalendarWrite).values(**row.model_dump())
                    .on_conflict_do_nothing().returning(CalendarWrite))).scalar_one_or_none()
        if inserted is None:
            # Another source can race on the same global write ID.
            existing = await session.get(CalendarWrite, row.id)
            if existing is not None:
                if existing.request_hash != row.request_hash:
                    raise WriteConflict()
                return existing, False
            raise WriteInProgress()
        await session.commit()
        return inserted, True


async def abandon(write_id: str, *, source_id: str,
                  operation: str) -> Literal["abandoned", "taken", "source_gone"]:
    """Take a free write ID as a final "not applied" record.

    Used for a chat card whose confirm died after claiming the card but before claiming its
    write: a confirm that is still alive then finds the ID taken at its own claim and sends nothing.
    Returns "taken" when a record exists. Removing a calendar deletes its finished records, so
    without the calendar a missing record proves nothing: then nothing is taken ("source_gone").
    Claims and removal hold the same source lock, so neither can slip between these checks.
    """
    now = utcnow()
    async with get_session_maker()() as session:
        await lock_source(session, source_id)
        if await session.get(CalendarWrite, write_id) is not None:
            return "taken"
        if await session.get(CalendarSource, source_id) is None:
            return "source_gone"
        inserted = (await session.execute(insert(CalendarWrite).values(
            id=write_id, source_id=source_id, operation=operation, request_hash=ABANDONED_REQUEST_HASH,
            status="not_applied", error_code="calendar_write_not_applied", started_at=now, finished_at=now)
            .on_conflict_do_nothing().returning(CalendarWrite.id))).scalar_one_or_none()
        await session.commit()
        return "taken" if inserted is None else "abandoned"


async def finish(write_id: str, *, status: str, error_code: str | None = None,
                 result_external_id: str | None = None, result_revision: str | None = None) -> CalendarWrite:
    if status not in {"running", "done", "failed", "unknown", "not_applied"}:
        raise ValueError("invalid_write_status")
    values = dict(status=status, error_code=error_code, result_external_id=result_external_id,
                  result_revision=result_revision, finished_at=utcnow())
    if status in {"done", "failed", "not_applied"}:
        values["request_json"] = None
    async with get_session_maker()() as session:
        row = (await session.execute(update(CalendarWrite).where(CalendarWrite.id == write_id,
               CalendarWrite.status.in_(["running", "unknown"]))
               .values(**values).returning(CalendarWrite))).scalar_one_or_none()
        if row is None:
            row = await session.get(CalendarWrite, write_id)
            if row is None:
                raise LookupError("calendar_unavailable")
        await session.commit()
        return row


async def mark_dispatch(write_id: str, *, request_json: str) -> bool:
    """Record the dispatch evidence and refresh its expiry clock in the same update.

    Returns False when a concurrent read already expired the record: the caller must then
    send nothing, because a check may already have reconciled the record.
    """
    async with get_session_maker()() as session:
        row = (await session.execute(update(CalendarWrite).where(CalendarWrite.id == write_id,
               CalendarWrite.status == "running").values(started_at=utcnow(), request_json=request_json)
               .returning(CalendarWrite.id))).scalar_one_or_none()
        await session.commit()
        return row is not None


async def get(write_id: str) -> CalendarWrite | None:
    async with get_session_maker()() as session:
        return await session.get(CalendarWrite, write_id)


async def expire_running(write_id: str, *, before: datetime) -> CalendarWrite | None:
    async with get_session_maker()() as session:
        await session.execute(update(CalendarWrite).where(CalendarWrite.id == write_id,
            CalendarWrite.status == "running", CalendarWrite.started_at < before)
            .values(status="unknown", error_code="calendar_write_unknown"))
        await session.commit()
        return await session.get(CalendarWrite, write_id)
