"""Validated calendar recurrence expansion using python-dateutil 4.0.0.

COUNT counts only existing instances, as required by RFC 5545 section 3.3.10.
Nonexistent local wall times are discarded without consuming COUNT. Preview and
persistence share this expansion. An ambiguous wall time occurs once, with the
earlier offset (fold=0).
"""

from datetime import date, datetime, time, timezone
from itertools import islice
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr

_ALLOWED = {'FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY', 'BYMONTHDAY', 'BYMONTH'}
_DAYS = {'MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'}
_WEEKDAYS = ('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU')
_LONGEST_MONTH = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _valid_wall(value: datetime) -> bool:
    return value.astimezone(timezone.utc).astimezone(value.tzinfo).replace(tzinfo=None) == value.replace(tzinfo=None)


def _reject_impossible(parts: dict[str, str], dtstart: datetime) -> None:
    """Refuse rules that can never produce a date.

    dateutil searches period by period up to year 9999 before it gives up, which blocks the
    API for seconds with a daily rule. Rules that only fail through leap years (Feb 29 with a
    monthly interval that never reaches one) remain and cost a fraction of a second.
    """
    freq, interval = parts['FREQ'], int(parts.get('INTERVAL', '1'))
    months = {int(v) for v in parts['BYMONTH'].split(',')} if 'BYMONTH' in parts else set(_LONGEST_MONTH)
    if freq == 'MONTHLY':
        months &= {(dtstart.month - 1 + k * interval) % 12 + 1 for k in range(12)}
    if 'BYMONTHDAY' in parts:
        days = {abs(int(v)) for v in parts['BYMONTHDAY'].split(',')}
    elif freq == 'MONTHLY' and 'BYDAY' not in parts:
        days = {dtstart.day}  # dateutil repeats the start day
    else:
        days = {1}
    if not any(day <= _LONGEST_MONTH[month] for month in months for day in days):
        raise ValueError('recurrence never occurs')
    if freq == 'DAILY' and interval % 7 == 0 and 'BYDAY' in parts and _WEEKDAYS[dtstart.weekday()] not in parts['BYDAY'].split(','):
        raise ValueError('recurrence never occurs')


def _parse(start: date | datetime, rule: str, through: date | datetime, zone: str | None):
    """Validate a rule and construct the parser and inclusive local bound."""
    timed = isinstance(start, datetime)
    if timed != isinstance(through, datetime):
        raise ValueError('start and bound must have the same precision')
    if timed:
        if start.tzinfo is not None or through.tzinfo is not None or not zone:
            raise ValueError('timed values must be naive local datetimes with a zone')
        try:
            tz = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('unknown timezone') from exc
        dtstart = start.replace(tzinfo=tz, fold=0)
        if not _valid_wall(dtstart):
            raise ValueError('nonexistent start time')
    else:
        if zone is not None:
            raise ValueError('date values cannot have a timezone')
        dtstart = datetime.combine(start, time.min)
    parts = {}
    for part in rule.split(';'):
        key, sep, value = part.partition('=')
        if not sep or key not in _ALLOWED or key in parts or not value:
            raise ValueError('invalid recurrence field')
        parts[key] = value
    if parts.get('FREQ') not in {'DAILY', 'WEEKLY', 'MONTHLY'}:
        raise ValueError('unsupported frequency')
    for key, maximum in (('INTERVAL', 366), ('COUNT', 10000)):
        if key in parts and (not parts[key].isascii() or not parts[key].isdigit() or not 1 <= int(parts[key]) <= maximum):
            raise ValueError('invalid recurrence limit')
    if 'COUNT' in parts and 'UNTIL' in parts:
        raise ValueError('COUNT and UNTIL are mutually exclusive')
    for key, lower, upper in (('BYMONTHDAY', -31, 31), ('BYMONTH', 1, 12)):
        if key in parts:
            values = parts[key].split(',')
            if len(values) > 31 or any(not v.lstrip('-').isascii() or not v.lstrip('-').isdigit() or not lower <= int(v) <= upper or int(v) == 0 for v in values):
                raise ValueError('invalid recurrence list')
    if 'BYDAY' in parts and (len(parts['BYDAY'].split(',')) > 7 or any(v not in _DAYS for v in parts['BYDAY'].split(','))):
        raise ValueError('invalid weekdays')
    _reject_impossible(parts, dtstart)
    try:
        # dateutil counts imaginary times, so enforce COUNT after wall-time validation.
        count = int(parts['COUNT']) if timed and 'COUNT' in parts else None
        parser_rule = ';'.join(f'{key}={value}' for key, value in parts.items() if not (count and key == 'COUNT'))
        recurrence = rrulestr(parser_rule, dtstart=dtstart)
        bound = through.replace(tzinfo=dtstart.tzinfo, fold=0) if timed else datetime.combine(through, time.max)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('invalid recurrence') from exc
    return recurrence, dtstart, bound, timed, count


def _counted_candidates(recurrence, bound: datetime, count: int):
    """Yield calendar candidates through the bound, counting only existing times."""
    existing = 0
    for value in recurrence:
        if value > bound:
            return
        yield value
        if _valid_wall(value):
            existing += 1
            if existing == count:
                return


def expand_page(
    start: date | datetime, rule: str, through: date | datetime, zone: str | None = None,
    *, cursor: date | datetime | None = None, limit: int = 100,
) -> tuple[list[date | datetime], date | datetime | None]:
    """Return at most limit candidates and a local cursor, including skipped gaps.

    A non-null cursor means another page must be requested, even if it turns out
    to be empty. Bind the cursor to the revision and target in the caller.
    """
    if not 1 <= limit <= 1000:
        raise ValueError('invalid page size')
    recurrence, dtstart, bound, timed, count = _parse(start, rule, through, zone)
    if cursor is not None:
        if isinstance(cursor, datetime) != timed:
            raise ValueError('invalid cursor precision')
        if timed:
            if cursor.tzinfo is not None:
                raise ValueError('cursor must be local')
            after = cursor.replace(tzinfo=dtstart.tzinfo, fold=0)
        else:
            after = datetime.combine(cursor, time.min)
        if after < dtstart or after > bound or recurrence.before(after, inc=True) != after:
            raise ValueError('invalid cursor')
    else:
        after = dtstart
    try:
        if count is not None:
            # At most COUNT existing candidates are scanned, including on resume.
            candidates = list(islice((value for value in _counted_candidates(recurrence, bound, count)
                                      if value > after or (cursor is None and value == after)), limit))
        else:
            candidates = list(islice(recurrence.xafter(after, inc=cursor is None), limit))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('invalid recurrence') from exc
    candidates = [value for value in candidates if value <= bound]
    values = [value for value in candidates if not timed or _valid_wall(value)]
    local_values = [value.replace(tzinfo=None) if timed else value.date() for value in values]
    next_cursor = None
    if len(candidates) == limit:
        last = candidates[-1]
        next_cursor = last.replace(tzinfo=None) if timed else last.date()
    return local_values, next_cursor


def expand(start: date | datetime, rule: str, through: date | datetime, zone: str | None = None) -> list[date | datetime]:
    """Expand through an inclusive bound; reject unsupported and invalid rules."""
    recurrence, dtstart, bound, timed, count = _parse(start, rule, through, zone)
    try:
        values = list(_counted_candidates(recurrence, bound, count)) if count is not None else recurrence.between(dtstart, bound, inc=True)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('invalid recurrence') from exc
    if timed:
        return [value for value in values if _valid_wall(value)]
    return [value.date() for value in values]
