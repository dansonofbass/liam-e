"""Transactional task-series accessors; callers own commit and rollback."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from db.models.task_series import TaskSeries


async def create_once(session: AsyncSession, row: TaskSeries) -> tuple[TaskSeries, bool]:
    result = await session.execute(
        insert(TaskSeries).values(**row.model_dump()).on_conflict_do_nothing(
            constraint='uq_task_series_scope_creation_key'
        ).returning(TaskSeries.id)
    )
    created = result.scalar_one_or_none() is not None
    result = await session.execute(select(TaskSeries).where(
        TaskSeries.scope == row.scope, TaskSeries.creation_key == row.creation_key
    ))
    return result.scalar_one(), created


async def get(session: AsyncSession, scope: str, series_id: str) -> TaskSeries | None:
    result = await session.execute(select(TaskSeries).where(TaskSeries.id == series_id, TaskSeries.scope == scope))
    return result.scalar_one_or_none()
