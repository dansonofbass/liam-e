from datetime import date, datetime

import pytest

from api.tasks.recurrence import expand, expand_page


def test_count_excludes_nonexistent_wall_times():
    values = expand(datetime(2024, 3, 30, 2, 30), 'FREQ=DAILY;COUNT=3', datetime(2024, 4, 4), 'Europe/Berlin')
    assert [(v.day, v.hour) for v in values] == [(30, 2), (1, 2), (2, 2)]


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


@pytest.mark.parametrize('start,rule', [
    (date(2026, 1, 1), 'FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30'),
    (date(2026, 1, 1), 'FREQ=MONTHLY;BYMONTHDAY=31;BYMONTH=4,6,9,11'),
    (date(2026, 1, 1), 'FREQ=WEEKLY;BYMONTHDAY=-30;BYMONTH=2'),
    (date(2026, 1, 15), 'FREQ=MONTHLY;INTERVAL=12;BYMONTH=3'),
    (date(2026, 1, 31), 'FREQ=MONTHLY;BYMONTH=2'),
    (date(2026, 1, 5), 'FREQ=DAILY;INTERVAL=14;BYDAY=TU'),
])
def test_rules_that_never_occur_are_rejected(start, rule):
    with pytest.raises(ValueError, match='never occurs'):
        expand_page(start, rule, date(2026, 3, 1), limit=10)


@pytest.mark.parametrize('start,rule,first', [
    (date(2026, 1, 1), 'FREQ=MONTHLY;BYMONTH=2;BYMONTHDAY=29', date(2028, 2, 29)),
    (date(2026, 1, 1), 'FREQ=MONTHLY;BYMONTHDAY=13;BYDAY=FR', date(2026, 2, 13)),
    (date(2026, 1, 31), 'FREQ=MONTHLY', date(2026, 1, 31)),
    (date(2026, 1, 5), 'FREQ=DAILY;INTERVAL=14;BYDAY=MO', date(2026, 1, 5)),
    (date(2026, 1, 15), 'FREQ=MONTHLY;INTERVAL=12;BYMONTH=1', date(2026, 1, 15)),
])
def test_sparse_rules_still_occur(start, rule, first):
    assert expand(start, rule, date(2029, 1, 1))[0] == first


def test_pages_include_gap_in_cursor_and_match_preview():
    start = datetime(2024, 3, 30, 2, 30)
    end = datetime(2024, 4, 5)
    rule = 'FREQ=DAILY;COUNT=5'
    cursor = None
    result = []
    while True:
        values, cursor = expand_page(start, rule, end, 'Europe/Berlin', cursor=cursor, limit=2)
        result.extend(values)
        if cursor is None:
            break
    assert result == [v.replace(tzinfo=None) for v in expand(start, rule, end, 'Europe/Berlin')]
    assert [v.day for v in result] == [30, 1, 2, 3, 4]


def test_page_rejects_non_candidate_cursor_and_invalid_limit():
    with pytest.raises(ValueError):
        expand_page(date(2024, 1, 1), 'FREQ=DAILY;INTERVAL=2', date(2024, 2, 1), cursor=date(2024, 1, 2))
    with pytest.raises(ValueError):
        expand_page(date(2024, 1, 1), 'FREQ=DAILY', date(2024, 2, 1), limit=0)


def test_invalid_start_and_zone():
    with pytest.raises(ValueError):
        expand(datetime(2024, 3, 31, 2, 30), 'FREQ=DAILY', datetime(2024, 4, 1), 'Europe/Berlin')
    with pytest.raises(ValueError):
        expand(datetime(2024, 1, 1), 'FREQ=DAILY', datetime(2024, 2, 1), 'Not/AZone')
