"""Transactional creation of unlinked personal task schedules.

The caller owns commit and rollback. Source references are intentionally not
accepted here until they can be verified within the same transaction.
"""

import hashlib
import json
from datetime import date, datetime

from db.accessors import task_schedule_revision, task_series
from db.models.task_schedule_revision import TaskScheduleRevision
from db.models.task_series import TaskSeries
from sqlmodel.ext.asyncio.session import AsyncSession

from api.tasks.recurrence import expand_page


class CreationConflict(ValueError):
    """A creation key was previously used for a different payload."""


async def create(
    session: AsyncSession, *, creation_key: str, title: str,
    start: date | datetime, zone: str | None = None, rule: str | None = None,
    description: str = '',
) -> tuple[TaskSeries, bool]:
    """Create a series once, with a deterministic payload hash and app scope."""
    if not creation_key or not title:
        raise ValueError('creation key and title are required')
    expand_page(start, rule or 'FREQ=DAILY;COUNT=1', start, zone, limit=1)
    payload = {'title': title, 'description': description, 'start': start.isoformat(),
               'timezone': zone, 'rrule': rule}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                       separators=(',', ':')).encode()).hexdigest()
    row = TaskSeries(scope='app', creation_key=creation_key, creation_hash=digest,
                     title=title, description=description)
    existing, created = await task_series.create_once(session, row)
    if not created:
        if existing.creation_hash != digest:
            raise CreationConflict('creation key belongs to a different payload')
        return existing, False
    await task_schedule_revision.add(session, TaskScheduleRevision(
        series_id=existing.id, version=1, start_local=start.isoformat(), timezone=zone, rrule=rule,
    ))
    return existing, True
