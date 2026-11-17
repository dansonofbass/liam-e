"""Index-only calendar tools. Source selection can only narrow the persisted turn scope."""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from db.accessors import calendar_occurrence, calendar_source
from fastapi import HTTPException
from api.routers.api.v1.calendar.occurrences import _decode, _encode
from api.routers.api.v1.calendar.schemas import OccurrenceOut
from api.routers.api.v1.calendar.sources import source_out


async def read_calendar(name, arguments, source_ids, timezone):
    ids = set(source_ids)
    wanted = arguments.get('source_ids', list(ids))
    if not isinstance(wanted, list) or not all(isinstance(id, str) for id in wanted) or not set(wanted) <= ids:
        return {'error': 'calendar_out_of_scope'}, []
    sources = {s.id: s for s in await calendar_source.list_active() if s.id in ids}
    if set(sources) != ids:
        return {'error': 'calendar_scope_revoked'}, []
    selected = [sources[id] for id in sorted(set(wanted))]
    if name == 'get_calendar_occurrence':
        row = await calendar_occurrence.get_visible(arguments.get('occurrence_id', ''))
        if row is None or row.source_id not in {s.id for s in selected}:
            return {'error': 'occurrence_not_found'}, []
        rows, more = [row], False
        start = end = coverage_start = coverage_end = None
    else:
        try:
            first, last = date.fromisoformat(arguments['from']), date.fromisoformat(arguments['to'])
            if not timedelta(0) < last - first <= timedelta(days=90):
                raise ValueError()
            zone = ZoneInfo(timezone)
            start, end = datetime.combine(first, time.min, zone), datetime.combine(last, time.min, zone)
            coverage_start = min(start, datetime.combine(first, time.min, UTC))
            coverage_end = max(end, datetime.combine(last, time.min, UTC))
            after = _decode(arguments['cursor']) if arguments.get('cursor') else None
            query = arguments.get('query', '')
            if not isinstance(query, str) or len(query) > 200:
                raise ValueError()
        except (ValueError, KeyError, TypeError, HTTPException):
            return {'error': 'calendar_window_invalid'}, []
        rows = await calendar_occurrence.page_visible(start=start, end=end, start_date=first, end_date=last,
            source_ids=[s.id for s in selected], after=after, limit=51) if selected else []
        more = len(rows) > 50
        rows = rows[:50]
    next_cursor = _encode(rows[-1]) if more else None
    if name != 'get_calendar_occurrence':
        rows = [row for row in rows if query.casefold() in row.title.casefold()
                and first <= (row.start_date or row.start_at.astimezone(zone).date()) < last]
    statuses = []
    for source in selected:
        status = (await source_out(source)).model_dump(mode='json')
        covered = bool(start and end and status['coverage_start'] and status['coverage_end'] and
            datetime.fromisoformat(status['coverage_start']) <= coverage_start and datetime.fromisoformat(status['coverage_end']) >= coverage_end)
        status['window_covered'] = covered
        statuses.append(status)
    return {'untrusted_calendar_data': {'occurrences': [OccurrenceOut.model_validate(row, from_attributes=True).model_dump(mode='json') for row in rows],
        'sources': statuses}, 'next_cursor': next_cursor, 'read_only': True,
        'note': 'Gespeicherter Index, keine Zusage zur Aktualität beim Anbieter. Fehlende Abdeckung und weitere Seiten ausdrücklich nennen.'}, [
        {'source_id': row.source_id, 'occurrence_id': row.id} for row in rows[:10]]
