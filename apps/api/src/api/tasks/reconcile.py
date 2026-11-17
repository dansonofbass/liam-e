"""Transactional, revision-locked materialization of a fixed recurrence window.

The caller owns the session transaction, including commit and rollback. This allows
other domain changes to participate in the same transaction. A cursor is bound to
both revision and target; callers must retry a stale request with current progress.
"""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from db.accessors import task_occurrence, task_schedule_revision, task_series
from db.models.task_occurrence import TaskOccurrence
from sqlmodel.ext.asyncio.session import AsyncSession

from api.tasks.recurrence import expand_page


class ReconcileConflict(ValueError):
    """The revision, target or supplied progress no longer matches."""


def _position(token: str | None, revision_id: str, target: str) -> str | None:
    if token is None:
        return None
    try:
        data = json.loads(token)
        if not isinstance(data, dict) or set(data) != {'revision', 'target', 'position'}:
            raise ValueError
        if data['revision'] != revision_id or data['target'] != target or not isinstance(data['position'], str):
            raise ValueError
        return data['position']
    except (ValueError, TypeError, KeyError) as exc:
        raise ReconcileConflict('invalid cursor') from exc


async def reconcile_batch(
    session: AsyncSession, *, scope: str, series_id: str, revision_id: str,
    started_at: datetime, cursor: str | None, limit: int = 100,
) -> tuple[str | None, bool]:
    """Materialize one page; persist its progress in the caller's transaction.

    ``started_at`` is the fixed run start in UTC; the inclusive horizon is 30
    days later. A completed run cannot yet be advanced to a subsequent horizon.
    """
    if started_at.tzinfo is None:
        raise ValueError('run start must be timezone-aware')
    target_dt = started_at.astimezone(UTC) + timedelta(days=30)
    target = target_dt.isoformat()
    series = await task_series.get(session, scope, series_id, lock=True)
    revision = await task_schedule_revision.get(session, revision_id, lock=True)
    if series is None or revision is None or revision.series_id != series_id or series.archived:
        raise ReconcileConflict('series or revision unavailable')
    if revision.reconcile_target is None:
        if cursor is not None:
            raise ReconcileConflict('unexpected cursor')
        revision.reconcile_target = target
    if revision.reconcile_target != target or revision.reconcile_cursor != cursor:
        raise ReconcileConflict('stale target or cursor')
    position = _position(cursor, revision_id, target)
    if position == 'done:rfc5545':
        return cursor, True
    if position == 'done':
        if 'T' not in revision.start_local.upper() or not any(part.startswith('COUNT=') for part in (revision.rrule or '').split(';')):
            return cursor, True
        # Old COUNT runs may have stopped before the valid tail. Replay in bounded
        # pages; original keys preserve existing occurrences and their state.
        position = None

    timed = 'T' in revision.start_local.upper()
    parser = datetime.fromisoformat if timed else date.fromisoformat
    start = parser(revision.start_local)
    end = target_dt.astimezone(ZoneInfo(revision.timezone)).replace(tzinfo=None) if timed else target_dt.astimezone(ZoneInfo(revision.timezone or 'UTC')).date()
    after = parser(position) if position is not None else None
    rule = revision.rrule or 'FREQ=DAILY;COUNT=1'
    values, next_position = expand_page(start, rule, end, revision.timezone, cursor=after, limit=limit)
    for value in values:
        due_at = value.replace(tzinfo=ZoneInfo(revision.timezone)).astimezone(UTC) if timed else None
        row = TaskOccurrence(series_id=series_id, revision_id=revision_id,
                             occurrence_key=value.isoformat(), due_local=value.isoformat(), due_at=due_at)
        await task_occurrence.insert_once(session, row)
    done = next_position is None
    new_cursor = json.dumps({'revision': revision_id, 'target': target,
                             'position': 'done:rfc5545' if done else next_position.isoformat()},
                            sort_keys=True, separators=(',', ':'))
    revision.reconcile_cursor = new_cursor
    session.add(revision)
    await session.flush()
    return new_cursor, done
