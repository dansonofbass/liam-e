"""List task occurrences and apply versioned state changes."""

import base64
import binascii
import json
from datetime import date, timedelta
from typing import Annotated, Literal

from db.accessors import task_occurrence
from db.engine import get_session_maker
from fastapi import APIRouter, Query

from api.errors import quiet_validation_route, refuse
from api.tasks import state
from .schemas import OccurrenceOut, OccurrencePage, VersionIn

router = APIRouter(route_class=quiet_validation_route(
    'task_invalid', 'Prüfe die Angaben zur Fälligkeit: höchstens 100 Einträge pro Seite.',
))


def encode_cursor(due: str, identifier: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([due, identifier], separators=(',', ':')).encode()).decode().rstrip('=')


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        if len(cursor) > 1024:
            raise ValueError
        raw = base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True)
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, str) and v for v in value):
            raise ValueError
        date.fromisoformat(value[0][:10])
        if len(value[0]) > 40 or len(value[1]) > 200:
            raise ValueError
        return value[0], value[1]
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise refuse(422, 'task_cursor_invalid', 'Die Aufgaben konnten nicht geladen werden. Öffne die Liste noch einmal.') from None


@router.get('', operation_id='tasks_occurrences_list', summary='List materialized task occurrences')
async def list_occurrences(
    status: Literal['open', 'completed', 'skipped', 'cancelled'] | None = None,
    due_from: date | None = None, due_to: date | None = None,
    cursor: str = '', limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> OccurrencePage:
    """Filter by inclusive local calendar dates; reading does not materialize."""
    if due_from and due_to and due_from > due_to:
        raise refuse(422, 'task_range_invalid', 'Der Zeitraum ist ungültig. Prüfe Anfang und Ende.')
    if due_to == date.max:
        raise refuse(422, 'task_range_invalid', 'Das Enddatum liegt zu weit in der Zukunft.')
    after = decode_cursor(cursor) if cursor else None
    async with get_session_maker()() as session:
        rows = await task_occurrence.list_page(session, scope='app', status=status,
            due_from=due_from.isoformat() if due_from else None,
            due_to=(due_to + timedelta(days=1)).isoformat() if due_to else None,
            after=after, limit=limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    return OccurrencePage(items=[OccurrenceOut.model_validate(row) for row in rows],
                          next_cursor=encode_cursor(rows[-1].due_local, rows[-1].id) if more else None)


async def _transition(occurrence_id: str, body: VersionIn, action: str) -> OccurrenceOut:
    try:
        async with get_session_maker()() as session:
            row = await state.transition(session, occurrence_id, version=body.version, action=action)
            result = OccurrenceOut.model_validate(row)
            await session.commit()
            return result
    except state.StateNotFound:
        raise refuse(404, 'task_not_found', 'Diese Aufgabe gibt es nicht mehr.') from None
    except state.StateConflict:
        raise refuse(409, 'task_version_conflict', 'Die Aufgabe wurde geändert. Lade sie noch einmal.') from None


@router.post('/{occurrence_id}/complete', operation_id='tasks_occurrence_complete', summary='Complete an occurrence')
async def complete(occurrence_id: str, body: VersionIn) -> OccurrenceOut:
    return await _transition(occurrence_id, body, 'complete')


@router.post('/{occurrence_id}/skip', operation_id='tasks_occurrence_skip', summary='Skip an occurrence')
async def skip(occurrence_id: str, body: VersionIn) -> OccurrenceOut:
    return await _transition(occurrence_id, body, 'skip')


@router.post('/{occurrence_id}/reopen', operation_id='tasks_occurrence_reopen', summary='Reopen an occurrence')
async def reopen(occurrence_id: str, body: VersionIn) -> OccurrenceOut:
    return await _transition(occurrence_id, body, 'reopen')
