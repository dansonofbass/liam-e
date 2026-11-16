"""Transactional access to task schedule revisions."""

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from db.models.task_schedule_revision import TaskScheduleRevision


async def add(session: AsyncSession, revision: TaskScheduleRevision) -> None:
    session.add(revision)
    await session.flush()


async def get(session: AsyncSession, revision_id: str, *, lock: bool = False) -> TaskScheduleRevision | None:
    query = select(TaskScheduleRevision).where(TaskScheduleRevision.id == revision_id)
    if lock:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one_or_none()
