"""Probe dateutil's raw recurrence behavior before adding a task adapter.

In particular, dateutil emits imaginary wall times and counts them toward COUNT;
consumers must not assume that its timezone-aware output is always valid.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from dateutil.rrule import rrulestr
from dateutil.tz import datetime_exists


def test_month_end_and_leap_day_are_skipped():
    start = datetime(2024, 1, 31)
    assert list(rrulestr('FREQ=MONTHLY;COUNT=4', dtstart=start)) == [
        datetime(2024, 1, 31), datetime(2024, 3, 31),
        datetime(2024, 5, 31), datetime(2024, 7, 31),
    ]
    assert list(rrulestr('FREQ=MONTHLY;BYMONTH=2;BYMONTHDAY=29;COUNT=2', dtstart=start)) == [
        datetime(2024, 2, 29), datetime(2028, 2, 29),
    ]


def test_berlin_gap_and_overlap_are_not_expanded():
    berlin = ZoneInfo('Europe/Berlin')
    gap = list(rrulestr('FREQ=DAILY;COUNT=3', dtstart=datetime(2024, 3, 30, 2, 30, tzinfo=berlin)))
    assert [datetime_exists(value) for value in gap] == [True, False, True]
    overlap = list(rrulestr('FREQ=DAILY;COUNT=3', dtstart=datetime(2024, 10, 26, 2, 30, tzinfo=berlin)))
    assert len(overlap) == 3
    assert overlap[1].fold == 0
    assert overlap[0].utcoffset() == overlap[1].utcoffset()
    assert overlap[1].utcoffset() != overlap[2].utcoffset()


def test_until_is_inclusive_and_aware_start_requires_utc_until():
    assert list(rrulestr('FREQ=DAILY;UNTIL=20240103', dtstart=datetime(2024, 1, 1))) == [
        datetime(2024, 1, 1), datetime(2024, 1, 2), datetime(2024, 1, 3),
    ]
    with pytest.raises(ValueError):
        rrulestr('FREQ=DAILY;UNTIL=20240103T100000', dtstart=datetime(2024, 1, 1, tzinfo=ZoneInfo('Europe/Berlin')))


def test_unknown_rrule_field_is_rejected():
    with pytest.raises(ValueError):
        rrulestr('FREQ=DAILY;UNKNOWN=1', dtstart=datetime(2024, 1, 1))
