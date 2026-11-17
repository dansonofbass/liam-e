"""Transactional task-series accessors; callers own commit and rollback."""

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from db.models.task_series import TaskSeries
from db.models.task_occurrence import TaskOccurrence
from db.models.task_schedule_revision import TaskScheduleRevision


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


async def list_page(
    session: AsyncSession, *, scope: str, due_from: str, due_to: str,
    archived: bool | None, source: str, source_account_id: str | None,
    after: str | None, limit: int,
) -> list[TaskSeries]:
    """Include schedules whose validity intersects the window, even before catch-up.

    Existing occurrences also qualify, including individually moved occurrences.
    Source references are deliberately not joined to live mail/account rows.
    """
    occurrence = select(TaskOccurrence.id).where(
        TaskOccurrence.series_id == TaskSeries.id, TaskOccurrence.due_local >= due_from,
        TaskOccurrence.due_local < due_to,
    ).exists()
    schedule = select(TaskScheduleRevision.id).where(
        TaskScheduleRevision.series_id == TaskSeries.id,
        TaskScheduleRevision.start_local < due_to,
        or_(TaskScheduleRevision.end_key.is_(None), TaskScheduleRevision.end_key >= due_from),
    ).exists()
    query = select(TaskSeries).where(TaskSeries.scope == scope, or_(occurrence, schedule))
    if archived is not None:
        query = query.where(TaskSeries.archived == archived)
    if source == 'unlinked':
        query = query.where(TaskSeries.source_message_id.is_(None))
    elif source == 'account':
        query = query.where(TaskSeries.source_account_id == source_account_id)
    if after is not None:
        query = query.where(TaskSeries.id > after)
    return list((await session.execute(query.order_by(TaskSeries.id).limit(limit))).scalars().all())


async def get(session: AsyncSession, scope: str, series_id: str, *, lock: bool = False) -> TaskSeries | None:
    query = select(TaskSeries).where(TaskSeries.id == series_id, TaskSeries.scope == scope)
    if lock:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one_or_none()
