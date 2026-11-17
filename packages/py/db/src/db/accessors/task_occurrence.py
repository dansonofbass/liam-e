"""Transactional access to materialized task occurrences."""

from datetime import datetime

from sqlalchemy import and_, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from db.models._common import utcnow
from db.models.task_occurrence import TaskOccurrence
from db.models.task_series import TaskSeries
from db.models.task_schedule_revision import TaskScheduleRevision


async def insert_once(session: AsyncSession, row: TaskOccurrence) -> bool:
    result = await session.execute(
        insert(TaskOccurrence).values(**row.model_dump()).on_conflict_do_nothing(
            constraint='uq_task_occurrence_revision_key'
        ).returning(TaskOccurrence.id)
    )
    return result.scalar_one_or_none() is not None


async def list_page(session: AsyncSession, *, scope: str, status: str | None, due_from: str | None,
                    due_to: str | None, after: tuple[str, str] | None, limit: int,
                    series_id: str | None = None) -> list[TaskOccurrence]:
    query = select(TaskOccurrence).join(TaskSeries, TaskOccurrence.series_id == TaskSeries.id).where(TaskSeries.scope == scope)
    if series_id is not None:
        query = query.where(TaskOccurrence.series_id == series_id)
    if status is not None:
        query = query.where(TaskOccurrence.status == status)
    if due_from is not None:
        query = query.where(TaskOccurrence.due_local >= due_from)
    if due_to is not None:
        query = query.where(TaskOccurrence.due_local < due_to)
    if after is not None:
        query = query.where(tuple_(TaskOccurrence.due_local, TaskOccurrence.id) > after)
    result = await session.execute(query.order_by(TaskOccurrence.due_local, TaskOccurrence.id).limit(limit))
    return list(result.scalars().all())


async def get(session: AsyncSession, occurrence_id: str) -> TaskOccurrence | None:
    return (await session.execute(select(TaskOccurrence).where(TaskOccurrence.id == occurrence_id).execution_options(populate_existing=True))).scalar_one_or_none()


async def cancel_future(session: AsyncSession, series_id: str, now: datetime) -> int:
    """One conditional update, using each revision's local date boundary."""
    zone = select(TaskScheduleRevision.timezone).where(
        TaskScheduleRevision.id == TaskOccurrence.revision_id).scalar_subquery()
    today = func.to_char(func.timezone(func.coalesce(zone, 'UTC'), now), 'YYYY-MM-DD')
    query = update(TaskOccurrence).where(TaskOccurrence.series_id == series_id,
        TaskOccurrence.status == 'open', or_(TaskOccurrence.due_at > now,
            and_(TaskOccurrence.due_at.is_(None), TaskOccurrence.due_local > today))).values(
                status='cancelled', version=TaskOccurrence.version + 1, updated_at=utcnow()).returning(TaskOccurrence.id)
    return len((await session.execute(query.execution_options(synchronize_session=False))).scalars().all())


async def transition(session: AsyncSession, occurrence_id: str, *, version: int, expected: str, target: str) -> bool:
    """Compare-and-swap a state without committing the caller's transaction."""
    result = await session.execute(
        update(TaskOccurrence).where(
            TaskOccurrence.id == occurrence_id,
            TaskOccurrence.version == version,
            TaskOccurrence.status == expected,
        ).values(status=target, version=version + 1, updated_at=utcnow()).returning(TaskOccurrence.id)
    )
    return result.scalar_one_or_none() is not None
