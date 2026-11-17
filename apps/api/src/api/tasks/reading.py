"""Read-only task projections; completeness never expands or materializes a rule."""

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from db.models.task_schedule_revision import TaskScheduleRevision


def validate_window(due_from: date, due_to: date) -> None:
    if due_to < due_from or due_to == date.max or (due_to - due_from).days > 365:
        raise ValueError('invalid window')


def complete_in_window(revisions: list[TaskScheduleRevision], due_from: date, due_to: date) -> bool:
    """Conservative proof of coverage, inclusive local dates, independent of pagination.

    A completed target covers a timed date only after that entire local day.
    Earlier windows may already be covered while a later catch-up page is pending.
    Legacy timed COUNT completion markers cannot certify their missing tail.
    """
    validate_window(due_from, due_to)
    end = (due_to + timedelta(days=1)).isoformat()
    for revision in revisions:
        if revision.start_local >= end or (revision.end_key is not None and revision.end_key < due_from.isoformat()):
            continue
        if revision.reconcile_cursor is None or revision.reconcile_target is None:
            return False
        try:
            data = json.loads(revision.reconcile_cursor)
            if data['revision'] != revision.id or data['target'] != revision.reconcile_target:
                return False
            position = data['position']
            timed = 'T' in revision.start_local.upper()
            if position.startswith('done'):
                if position == 'done' and timed and any(part.startswith('COUNT=') for part in (revision.rrule or '').split(';')):
                    return False
                target = datetime.fromisoformat(revision.reconcile_target)
                local = target.astimezone(ZoneInfo(revision.timezone or 'UTC'))
                covered = local.replace(tzinfo=None).isoformat() if timed else local.date().isoformat()
            else:
                covered = position
            required = datetime.combine(due_to + timedelta(days=1), time.min).isoformat() if timed else due_to.isoformat()
            if revision.end_key is not None:
                required = min(required, revision.end_key)
            if covered < required:
                return False
        except (ValueError, TypeError, KeyError, AttributeError):
            return False
    return True
