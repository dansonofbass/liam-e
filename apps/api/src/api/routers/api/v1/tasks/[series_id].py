"""Read a scoped task series without changing its materialization state."""

from datetime import date, timedelta
from typing import Annotated, Literal

from db.accessors import task_occurrence, task_series
from db.engine import get_session_maker
from fastapi import APIRouter, Query

from api.errors import refuse
from .occurrences import decode_cursor, encode_cursor
from .route import checked_window, series_out
from .schemas import OccurrenceOut, OccurrencePage, SeriesDetail

router = APIRouter()


@router.get('', operation_id='tasks_get', summary='Read a task series and a page of its occurrences')
async def get_task(
    series_id: str, due_from: date, due_to: date,
    status: Literal['open', 'completed', 'skipped', 'cancelled'] | None = None,
    cursor: Annotated[str, Query(max_length=1024)] = '',
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SeriesDetail:
    window = checked_window(due_from, due_to)
    after = decode_cursor(cursor) if cursor else None
    async with get_session_maker()() as session:
        row = await task_series.get(session, 'app', series_id)
        if row is None:
            raise refuse(404, 'task_not_found', 'Diese Aufgabe gibt es nicht mehr.')
        series = await series_out(session, row, due_from, due_to)
        rows = await task_occurrence.list_page(session, scope='app', series_id=series_id,
            status=status, due_from=due_from.isoformat(), due_to=(due_to + timedelta(days=1)).isoformat(),
            after=after, limit=limit + 1)
        more = len(rows) > limit
        rows = rows[:limit]
        return SeriesDetail(window=window, series=series, occurrences=OccurrencePage(
            items=[OccurrenceOut.model_validate(item) for item in rows],
            next_cursor=encode_cursor(rows[-1].due_local, rows[-1].id) if more else None,
        ))
