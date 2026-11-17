"""Versioned archive and final deletion in a caller-owned transaction."""

from datetime import UTC, datetime

from db.accessors import task_occurrence, task_series
from db.models.task_series import TaskSeries
from sqlmodel.ext.asyncio.session import AsyncSession

from api.tasks.state import StateConflict, StateNotFound


class DeleteConfirmationRequired(ValueError):
    """The request did not explicitly acknowledge permanent history loss."""


async def archive(session: AsyncSession, series_id: str, *, expected_version: int,
                  now: datetime | None = None) -> TaskSeries:
    row = await task_series.get(session, 'app', series_id, lock=True)
    if row is None:
        raise StateNotFound('series not found')
    if row.version != expected_version:
        raise StateConflict('series version changed')
    if row.archived:
        return row
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError('current time must be timezone-aware')
    if not await task_series.archive(session, 'app', series_id, expected_version):
        raise StateConflict('series version changed')
    await task_occurrence.cancel_future(session, series_id, instant)
    await session.refresh(row)
    return row


async def delete(session: AsyncSession, series_id: str, *, expected_version: int,
                 confirm_history_loss: bool) -> None:
    if confirm_history_loss is not True:
        raise DeleteConfirmationRequired('explicit confirmation required')
    row = await task_series.get(session, 'app', series_id, lock=True)
    if row is None:
        raise StateNotFound('series not found')
    if row.version != expected_version:
        raise StateConflict('series version changed')
    if not await task_series.delete_history(session, 'app', series_id, expected_version):
        raise StateConflict('series version changed')
