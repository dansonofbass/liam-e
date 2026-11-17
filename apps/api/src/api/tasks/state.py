"""Transactional state changes for personal task occurrences."""

from db.accessors import task_occurrence, task_series
from db.models.task_occurrence import TaskOccurrence
from sqlmodel.ext.asyncio.session import AsyncSession


class StateNotFound(ValueError):
    """The occurrence is not in the app scope."""


class StateConflict(ValueError):
    """The expected version or state no longer matches."""


async def transition(session: AsyncSession, occurrence_id: str, *, version: int, action: str) -> TaskOccurrence:
    """Apply a versioned transition without committing the caller's transaction."""
    if action not in {'complete', 'skip', 'reopen'}:
        raise ValueError('unsupported action')
    occurrence = await task_occurrence.get(session, occurrence_id)
    if occurrence is None or await task_series.get(session, 'app', occurrence.series_id) is None:
        raise StateNotFound('occurrence not found')
    if action == 'complete' and occurrence.status == 'completed':
        return occurrence
    expected = occurrence.status if action == 'reopen' else 'open'
    if action == 'reopen' and expected not in {'completed', 'skipped'}:
        raise StateConflict('occurrence is not closed')
    target = {'complete': 'completed', 'skip': 'skipped', 'reopen': 'open'}[action]
    if not await task_occurrence.transition(session, occurrence_id, version=version, expected=expected, target=target):
        raise StateConflict('occurrence version or state changed')
    await session.refresh(occurrence)
    return occurrence
