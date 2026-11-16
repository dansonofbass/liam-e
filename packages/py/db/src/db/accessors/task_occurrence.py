"""Transactional access to materialized task occurrences."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from db.models.task_occurrence import TaskOccurrence


async def insert_once(session: AsyncSession, row: TaskOccurrence) -> bool:
    result = await session.execute(
        insert(TaskOccurrence).values(**row.model_dump()).on_conflict_do_nothing(
            constraint='uq_task_occurrence_revision_key'
        ).returning(TaskOccurrence.id)
    )
    return result.scalar_one_or_none() is not None


async def get(session: AsyncSession, occurrence_id: str) -> TaskOccurrence | None:
    return (await session.execute(select(TaskOccurrence).where(TaskOccurrence.id == occurrence_id))).scalar_one_or_none()
