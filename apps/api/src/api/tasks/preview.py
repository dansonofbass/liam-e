"""Read-only bounded recurrence preview using the materialization parser."""

from calendar import monthrange
from datetime import date, datetime
from itertools import islice, takewhile

from api.tasks.recurrence import _counted_candidates, _parse, _valid_wall, expand_page


def preview(start: date | datetime, rule: str | None, through: date | datetime,
            zone: str, *, limit: int = 100) -> dict:
    start_day = start.date() if isinstance(start, datetime) else start
    through_day = through.date() if isinstance(through, datetime) else through
    if not zone or through < start or (through_day - start_day).days > 365:
        raise ValueError('invalid preview window')
    rule = rule or 'FREQ=DAILY;COUNT=1'
    values, cursor = expand_page(start, rule, through, zone, limit=limit)
    recurrence, dtstart, bound, timed, count = _parse(start, rule, through, zone)
    candidates = _counted_candidates(recurrence, bound, count) if count is not None else recurrence
    examined = list(islice(takewhile(lambda value: value <= bound, candidates), limit))
    exceptions = [{'local': value.replace(tzinfo=None).isoformat(), 'reason': 'nonexistent_time',
                   'monthday': None} for value in examined if timed and not _valid_wall(value)]
    parts = dict(part.split('=', 1) for part in rule.split(';'))
    # dateutil omits invalid month days before yielding candidates. Describe them
    # separately, only within the examined portion of a monthly schedule.
    if parts['FREQ'] == 'MONTHLY':
        exhausted = 'COUNT' in parts and len(values) >= int(parts['COUNT'])
        stop = examined[-1].date() if cursor is not None or exhausted else bound.date()
        if 'UNTIL' in parts:
            until = parts['UNTIL']
            stop = min(stop, date(int(until[:4]), int(until[4:6]), int(until[6:8])))
        month = dtstart.year * 12 + dtstart.month - 1
        last = stop.year * 12 + stop.month - 1
        interval = int(parts.get('INTERVAL', '1'))
        days = [int(v) for v in parts['BYMONTHDAY'].split(',')] if 'BYMONTHDAY' in parts else ([] if 'BYDAY' in parts else [dtstart.day])
        months = {int(v) for v in parts['BYMONTH'].split(',')} if 'BYMONTH' in parts else set(range(1, 13))
        while month <= last:
            year, index = divmod(month, 12)
            number = index + 1
            length = monthrange(year, number)[1]
            if number in months:
                for day in sorted(set(days)):
                    if abs(day) > length:
                        exceptions.append({'local': f'{year:04d}-{number:02d}',
                                           'reason': 'invalid_date', 'monthday': day})
            month += interval
    return {'occurrences': [value.isoformat() for value in values],
            'exceptions': sorted(exceptions, key=lambda item: item['local']),
            'through': through.isoformat(), 'complete': cursor is None}
