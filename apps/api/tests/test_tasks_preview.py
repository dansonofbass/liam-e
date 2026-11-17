"""Preview uses the persisted recurrence semantics without opening a database."""

import pytest


@pytest.mark.parametrize('start,through,rule,expected', [
    ('2024-03-30T02:30:00', '2024-04-04T02:30:00', 'FREQ=DAILY;COUNT=3',
     ['2024-03-30T02:30:00', '2024-04-01T02:30:00', '2024-04-02T02:30:00']),
    ('2024-10-26T02:30:00', '2024-10-29T02:30:00', 'FREQ=DAILY;COUNT=3',
     ['2024-10-26T02:30:00', '2024-10-27T02:30:00', '2024-10-28T02:30:00']),
    ('2024-01-31', '2024-05-31', 'FREQ=MONTHLY;COUNT=3',
     ['2024-01-31', '2024-03-31', '2024-05-31']),
    ('2023-12-29', '2024-03-30', 'FREQ=MONTHLY;COUNT=4',
     ['2023-12-29', '2024-01-29', '2024-02-29', '2024-03-29']),
    ('2024-01-01', '2024-01-05', 'FREQ=DAILY;UNTIL=20240103',
     ['2024-01-01', '2024-01-02', '2024-01-03']),
])
def test_preview_calendar_fixtures(client, start, through, rule, expected):
    response = client.post('/api/v1/tasks/preview', json={
        'start': start, 'through': through, 'rrule': rule, 'timezone': 'Europe/Berlin',
    })
    assert response.status_code == 200
    assert response.json()['occurrences'] == expected
    assert response.json()['complete']


def test_preview_explains_gap_and_missing_month_day(client):
    gap = client.post('/api/v1/tasks/preview', json={
        'start': '2024-03-30T02:30:00', 'through': '2024-04-04T02:30:00',
        'rrule': 'FREQ=DAILY;COUNT=3', 'timezone': 'Europe/Berlin',
    }).json()
    assert gap['exceptions'] == [{'local': '2024-03-31T02:30:00', 'reason': 'nonexistent_time', 'monthday': None}]
    month = client.post('/api/v1/tasks/preview', json={
        'start': '2024-01-31', 'through': '2024-02-29',
        'rrule': 'FREQ=MONTHLY', 'timezone': 'UTC',
    }).json()
    assert month['exceptions'] == [{'local': '2024-02', 'reason': 'invalid_date', 'monthday': 31}]


@pytest.mark.parametrize('change', [
    {'start': '2024-03-31T02:30:00', 'through': '2024-04-01T02:30:00'},
    {'timezone': 'Not/AZone'}, {'rrule': 'FREQ=YEARLY'},
    {'rrule': 'FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30'},
    {'through': '2026-01-01'}, {'limit': 101}, {'scope': 'other'},
])
def test_preview_rejects_invalid_input(client, change):
    response = client.post('/api/v1/tasks/preview', json={
        'start': '2024-01-01', 'through': '2024-02-01',
        'rrule': 'FREQ=DAILY', 'timezone': 'Europe/Berlin', **change,
    })
    assert response.status_code == 422


@pytest.mark.parametrize('start,through,status', [
    ('2024-01-01', '2024-12-31', 200),
    ('2024-01-01', '2025-01-01', 422),
    ('2024-01-01T07:00:00', '2024-12-31T23:00:00', 200),
    ('2024-01-01T07:00:00', '2025-01-01T01:00:00', 422),
])
def test_preview_inclusive_window_limit(client, start, through, status):
    response = client.post('/api/v1/tasks/preview', json={
        'start': start, 'through': through, 'timezone': 'Europe/Berlin',
    })
    assert response.status_code == status


def test_preview_marks_bounded_page_incomplete(client):
    response = client.post('/api/v1/tasks/preview', json={
        'start': '2024-01-01', 'through': '2024-02-01',
        'rrule': 'FREQ=DAILY', 'timezone': 'UTC', 'limit': 2,
    })
    assert response.status_code == 200
    assert response.json()['occurrences'] == ['2024-01-01', '2024-01-02']
    assert not response.json()['complete']
