"""Short transactions for claims and outcomes; never retry provider writes."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from db.accessors._calendar_lock import lock_source
from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.calendar_write import CalendarWrite


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


async def finish(write_id: str, *, status: str, error_code: str | None = None,
                 result_external_id: str | None = None, result_revision: str | None = None) -> CalendarWrite:
    if status not in {"running", "done", "failed", "unknown", "not_applied"}:
        raise ValueError("invalid_write_status")
    values = dict(status=status, error_code=error_code, result_external_id=result_external_id,
                  result_revision=result_revision, finished_at=utcnow())
    if status in {"done", "failed", "not_applied"}:
        values["request_json"] = None
    async with get_session_maker()() as session:
        row = (await session.execute(update(CalendarWrite).where(CalendarWrite.id == write_id)
               .values(**values).returning(CalendarWrite))).scalar_one()
        await session.commit()
        return row


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
