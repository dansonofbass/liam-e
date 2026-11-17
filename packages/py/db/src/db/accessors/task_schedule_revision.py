"""Transactional access to task schedule revisions."""

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from db.models.task_schedule_revision import TaskScheduleRevision


async def add(session: AsyncSession, revision: TaskScheduleRevision) -> None:
    session.add(revision)
    await session.flush()


async def get_by_version(session: AsyncSession, series_id: str, version: int) -> TaskScheduleRevision | None:
    query = select(TaskScheduleRevision).where(
        TaskScheduleRevision.series_id == series_id, TaskScheduleRevision.version == version
    )
    return (await session.execute(query)).scalar_one_or_none()


async def list_for_series(session: AsyncSession, series_id: str) -> list[TaskScheduleRevision]:
    query = select(TaskScheduleRevision).where(TaskScheduleRevision.series_id == series_id).order_by(TaskScheduleRevision.version)
    return list((await session.execute(query)).scalars().all())


async def current(session: AsyncSession, series_id: str) -> TaskScheduleRevision | None:
    query = select(TaskScheduleRevision).where(TaskScheduleRevision.series_id == series_id).order_by(TaskScheduleRevision.version.desc()).limit(1).execution_options(populate_existing=True)
    return (await session.execute(query)).scalar_one_or_none()


async def get(session: AsyncSession, revision_id: str, *, lock: bool = False) -> TaskScheduleRevision | None:
    query = select(TaskScheduleRevision).where(TaskScheduleRevision.id == revision_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(query)).scalar_one_or_none()
