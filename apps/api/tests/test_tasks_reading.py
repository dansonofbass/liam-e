"""Completeness describes only the requested local calendar window."""

import json
from datetime import date

from db.models.task_schedule_revision import TaskScheduleRevision

from api.tasks.reading import complete_in_window


def revision(start='2024-01-01', zone=None, position='done:rfc5545:2024-01-31'):
    row = TaskScheduleRevision(series_id='s', version=1, start_local=start, timezone=zone,
                               reconcile_target='2024-01-31T00:00:00+00:00')
    row.reconcile_cursor = json.dumps({'revision': row.id, 'target': row.reconcile_target, 'position': position})
    return row


def test_date_window_legacy_utc_and_partial_progress():
    row = revision()
    assert complete_in_window([row], date(2024, 1, 1), date(2024, 1, 31))
    assert not complete_in_window([row], date(2024, 1, 1), date(2024, 2, 1))
    row = revision(position='2024-01-10')
    assert complete_in_window([row], date(2024, 1, 1), date(2024, 1, 10))
    assert not complete_in_window([row], date(2024, 1, 1), date(2024, 1, 11))


def test_timed_window_requires_whole_local_day_and_count_repair():
    row = revision('2024-01-01T12:00:00', 'Europe/Berlin')
    assert complete_in_window([row], date(2024, 1, 1), date(2024, 1, 30))
    assert not complete_in_window([row], date(2024, 1, 1), date(2024, 1, 31))
    row = revision('2024-01-01T12:00:00', 'Europe/Berlin', position='done')
    row.rrule = 'FREQ=DAILY;COUNT=3'
    assert not complete_in_window([row], date(2024, 1, 1), date(2024, 1, 5))


def test_future_schedule_and_unmaterialized_schedule():
    row = revision('2024-02-01')
    row.reconcile_cursor = None
    assert complete_in_window([row], date(2024, 1, 1), date(2024, 1, 31))
    assert not complete_in_window([row], date(2024, 2, 1), date(2024, 2, 2))
