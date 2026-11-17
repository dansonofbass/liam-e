"""Read a scoped task series without changing its materialization state."""

from datetime import date, timedelta
from typing import Annotated, Literal

from db.accessors import task_occurrence, task_series
from db.engine import get_session_maker
from fastapi import APIRouter, Query, Response

from api.errors import refuse
from api.tasks import lifecycle
from api.tasks.state import StateConflict, StateNotFound
from .occurrences import decode_cursor, encode_cursor
from .route import checked_window, series_out
from .schemas import DeleteIn, OccurrenceOut, OccurrencePage, SeriesDetail, SeriesStateOut, SeriesVersionIn

router = APIRouter()


def lifecycle_error(exc: ValueError):
    if isinstance(exc, StateNotFound):
        return refuse(404, 'task_not_found', 'Diese Aufgabe gibt es nicht mehr.')
    if isinstance(exc, StateConflict):
        return refuse(409, 'task_version_conflict', 'Die Aufgabe wurde geändert. Lade sie noch einmal.')
    return refuse(422, 'task_delete_confirmation_required', 'Bestätige, dass die Aufgabe mit ihrem gesamten Verlauf endgültig gelöscht werden soll.')


@router.post('/archive', operation_id='tasks_archive', summary='Archive a task and cancel open future occurrences')
async def archive_task(series_id: str, body: SeriesVersionIn) -> SeriesStateOut:
    try:
        async with get_session_maker()() as session:
            row = await lifecycle.archive(session, series_id, expected_version=body.expected_version)
            result = SeriesStateOut(id=row.id, version=row.version, archived=row.archived)
            await session.commit()
            return result
    except (StateNotFound, StateConflict) as exc:
        raise lifecycle_error(exc) from None


@router.delete('', operation_id='tasks_delete', summary='Permanently delete a task and its history', status_code=204)
async def delete_task(series_id: str, body: DeleteIn) -> Response:
    try:
        async with get_session_maker()() as session:
            await lifecycle.delete(session, series_id, expected_version=body.expected_version,
                                   confirm_history_loss=body.confirm_history_loss)
            await session.commit()
            return Response(status_code=204)
    except (StateNotFound, StateConflict, lifecycle.DeleteConfirmationRequired) as exc:
        raise lifecycle_error(exc) from None


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
