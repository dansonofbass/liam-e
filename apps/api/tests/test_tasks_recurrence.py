from datetime import date, datetime

import pytest

from api.tasks.recurrence import expand


def test_count_includes_skipped_gap_candidate():
    values = expand(datetime(2024, 3, 30, 2, 30), 'FREQ=DAILY;COUNT=3', datetime(2024, 4, 4), 'Europe/Berlin')
    assert [(v.day, v.hour) for v in values] == [(30, 2), (1, 2)]


def test_month_end_and_leap_year():
    assert expand(date(2024, 1, 31), 'FREQ=MONTHLY;COUNT=3', date(2024, 8, 1)) == [date(2024, 1, 31), date(2024, 3, 31), date(2024, 5, 31)]
    assert expand(date(2024, 2, 29), 'FREQ=MONTHLY;BYMONTH=2;BYMONTHDAY=29;COUNT=2', date(2029, 1, 1)) == [date(2024, 2, 29), date(2028, 2, 29)]


def test_until_and_overlap():
    assert expand(date(2024, 1, 1), 'FREQ=DAILY;UNTIL=20240103', date(2024, 1, 5)) == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    result = expand(datetime(2024, 10, 26, 2, 30), 'FREQ=DAILY;COUNT=3', datetime(2024, 10, 30), 'Europe/Berlin')
    assert len(result) == 3 and result[1].fold == 0


@pytest.mark.parametrize('rule', ['FREQ=YEARLY', 'FREQ=DAILY;INTERVAL=0', 'FREQ=DAILY;BYHOUR=2', 'FREQ=DAILY;COUNT=2;COUNT=3', 'FREQ=DAILY;COUNT=2;UNTIL=20240101'])
def test_invalid_rules(rule):
    with pytest.raises(ValueError):
        expand(date(2024, 1, 1), rule, date(2024, 2, 1))


def test_invalid_start_and_zone():
    with pytest.raises(ValueError):
        expand(datetime(2024, 3, 31, 2, 30), 'FREQ=DAILY', datetime(2024, 4, 1), 'Europe/Berlin')
    with pytest.raises(ValueError):
        expand(datetime(2024, 1, 1), 'FREQ=DAILY', datetime(2024, 2, 1), 'Not/AZone')
