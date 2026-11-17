"""Transactional state changes for personal task occurrences."""

from datetime import UTC, datetime

from db.accessors import task_occurrence, task_schedule_revision, task_series
from db.models.task_occurrence import TaskOccurrence
from sqlmodel.ext.asyncio.session import AsyncSession

from api.tasks.dates import is_future


class StateNotFound(ValueError):
    """The occurrence is not in the app scope."""


class StateConflict(ValueError):
    """The expected version or state no longer matches."""


async def transition(session: AsyncSession, occurrence_id: str, *, version: int, action: str) -> TaskOccurrence:
    """Apply a versioned transition without committing the caller's transaction."""
    if action not in {'complete', 'skip', 'reopen'}:
        raise ValueError('unsupported action')
    occurrence = await task_occurrence.get(session, occurrence_id)
    if occurrence is None:
        raise StateNotFound('occurrence not found')
    series = await task_series.get(session, 'app', occurrence.series_id, lock=True)
    if series is None:
        raise StateNotFound('occurrence not found')
    # Archive/delete/revision changes take this same lock. Refresh the instance
    # after waiting so an earlier read cannot overwrite their decisions.
    occurrence = await task_occurrence.get(session, occurrence_id)
    if occurrence is None:
        raise StateNotFound('occurrence not found')
    if action == 'reopen' and series.archived:
        revision = await task_schedule_revision.get(session, occurrence.revision_id)
        if is_future(occurrence.due_local, revision.timezone if revision else None, datetime.now(UTC)):
            raise StateConflict('archived future occurrence cannot reopen')
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
