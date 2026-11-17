"""Versioned occurrence moves and schedule splits in caller-owned transactions.

Text belongs to the series in the current schema. This endpoint edits schedules,
not text; no implicit title/note changes can alter historical occurrences.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from db.accessors import task_occurrence, task_schedule_revision, task_series
from db.models.task_schedule_revision import TaskScheduleRevision
from sqlmodel.ext.asyncio.session import AsyncSession

from api.tasks.dates import is_future
from api.tasks.reading import complete_in_window
from api.tasks.reconcile import reconcile_batch
from api.tasks.recurrence import expand_page
from api.tasks.state import StateConflict, StateNotFound


class RevisionConflict(StateConflict):
    """The replacement schedule collides with a completed occurrence."""


def parse_local(value: str) -> date | datetime:
    return datetime.fromisoformat(value) if 'T' in value.upper() else date.fromisoformat(value)


def contains(start: date | datetime, rule: str | None, zone: str, target: date | datetime) -> bool:
    """Use the same COUNT/DST semantics as persistence, including sparse rules."""
    if target < start:
        return False
    cursor = None
    while True:
        values, cursor = expand_page(start, rule or 'FREQ=DAILY;COUNT=1', target, zone, cursor=cursor, limit=1000)
        if target in values:
            return True
        if cursor is None:
            return False


async def patch(
    session: AsyncSession, series_id: str, *, expected_version: int,
    occurrence_id: str, expected_occurrence_version: int, scope: str, start: str,
    timezone: str | None = None, rrule: str | None = None, rule_supplied: bool = False,
    now: datetime | None = None,
) -> tuple[int, str]:
    """Return new series version and affected revision; never commit here."""
    if scope not in {'occurrence', 'this_and_following'}:
        raise ValueError('invalid change scope')
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError('current time must be timezone-aware')
    value = parse_local(start)
    series = await task_series.get(session, 'app', series_id, lock=True)
    if series is None:
        raise StateNotFound('series not found')
    if series.archived or series.version != expected_version:
        raise StateConflict('series version or status changed')
    occurrence = await task_occurrence.get(session, occurrence_id)
    if occurrence is None or occurrence.series_id != series_id:
        raise StateNotFound('occurrence not found')
    if occurrence.status != 'open' or occurrence.version != expected_occurrence_version:
        raise StateConflict('occurrence version or status changed')
    revision = await task_schedule_revision.get(session, occurrence.revision_id, lock=True)
    if revision is None:
        raise StateNotFound('revision not found')
    if scope == 'occurrence':
        if timezone is not None or rule_supplied or isinstance(value, datetime) != ('T' in revision.start_local.upper()):
            raise ValueError('single changes retain precision, timezone and rule')
        zone = revision.timezone or 'UTC'
        expand_page(value, 'FREQ=DAILY;COUNT=1', value, zone, limit=1)
        due_at = value.replace(tzinfo=ZoneInfo(zone), fold=0).astimezone(UTC) if isinstance(value, datetime) else None
        if not await task_occurrence.move(session, occurrence.id, expected_occurrence_version, value.isoformat(), due_at):
            raise StateConflict('occurrence changed')
        if not await task_series.bump_version(session, 'app', series_id, expected_version):
            raise StateConflict('series changed')
        return expected_version + 1, revision.id

    current = await task_schedule_revision.current(session, series_id)
    if current is None or current.id != revision.id or revision.end_key is not None:
        raise StateConflict('only the current schedule may be split')
    # Do not reinterpret past instances or individually moved past exceptions.
    if not is_future(occurrence.occurrence_key, revision.timezone, instant) or not is_future(occurrence.due_local, revision.timezone, instant):
        raise StateConflict('split must start at a future occurrence')
    zone = timezone if timezone is not None else revision.timezone
    if not zone:
        raise ValueError('new revision requires a timezone')
    rule = rrule if rule_supplied else revision.rrule
    first, _ = expand_page(value, rule or 'FREQ=DAILY;COUNT=1', value, zone, limit=1)
    if first != [value]:
        raise ValueError('start must match the replacement rule')
    if not is_future(value.isoformat(), zone, instant):
        raise ValueError('new schedule must start in the future')
    if value.isoformat()[:10] < occurrence.occurrence_key[:10]:
        raise ValueError('new schedule cannot start before the split day')
    split_day = date.fromisoformat(occurrence.occurrence_key[:10])
    closed = revision.model_copy(update={'end_key': occurrence.occurrence_key})
    if not complete_in_window([closed], split_day, split_day):
        raise StateConflict('reconcile preceding history before splitting')

    for completed in await task_occurrence.completed_for_series(session, series_id):
        if isinstance(value, datetime):
            target = (completed.due_at.astimezone(ZoneInfo(zone)).replace(tzinfo=None)
                      if completed.due_at is not None else datetime.combine(date.fromisoformat(completed.due_local), value.time()))
        else:
            target = completed.due_at.astimezone(ZoneInfo(zone)).date() if completed.due_at is not None else date.fromisoformat(completed.due_local)
        if isinstance(value, datetime) and completed.due_at is not None:
            # An overlap always uses fold=0; the same wall value in fold=1 is
            # not the same instant and therefore not a timed collision.
            if target.replace(tzinfo=ZoneInfo(zone), fold=0).astimezone(UTC) != completed.due_at:
                continue
        if contains(value, rule, zone, target):
            raise RevisionConflict('replacement collides with completed history')

    # All checks precede the first write, including collision checks beyond the
    # initial 30-day page. The series lock excludes state/reconcile/lifecycle races.
    if not await task_series.bump_version(session, 'app', series_id, expected_version):
        raise StateConflict('series changed')
    revision.end_key = occurrence.occurrence_key  # Exclusive original-key boundary.
    session.add(revision)
    await task_occurrence.remove_open_suffix(session, revision.id, occurrence.occurrence_key, instant)
    replacement = TaskScheduleRevision(series_id=series_id, version=revision.version + 1,
        start_local=value.isoformat(), timezone=zone, rrule=rule)
    await task_schedule_revision.add(session, replacement)
    await reconcile_batch(session, scope='app', series_id=series_id, revision_id=replacement.id,
                          started_at=instant, cursor=None)
    return expected_version + 1, replacement.id
