"""Create personal task series."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from db.accessors import task_schedule_revision, task_series
from db.engine import get_session_maker
from fastapi import APIRouter, Query

from api.errors import refuse
from api.tasks import create, reconcile
from api.tasks.recurrence import expand_page
from api.tasks.reading import complete_in_window, validate_window
from .schemas import ScheduleOut, SeriesOut, SeriesPage, TaskCreate, TaskCreated, TaskWindow

router = APIRouter()


async def series_out(session, row, due_from: date, due_to: date) -> SeriesOut:
    revisions = await task_schedule_revision.list_for_series(session, row.id)
    return SeriesOut(**row.model_dump(), schedule=ScheduleOut.model_validate(revisions[-1]) if revisions else None,
                     complete=bool(revisions) and complete_in_window(revisions, due_from, due_to))


def checked_window(due_from: date, due_to: date) -> TaskWindow:
    try:
        validate_window(due_from, due_to)
    except ValueError:
        raise refuse(422, 'task_range_invalid', 'Der Zeitraum ist ungültig. Wähle höchstens 366 Tage.') from None
    return TaskWindow(due_from=due_from, due_to=due_to)


@router.get('', operation_id='tasks_list', summary='List task series in a local date window')
async def list_tasks(
    due_from: date, due_to: date,
    status: Literal['active', 'archived'] | None = None,
    source: Literal['all', 'unlinked', 'account'] = 'all',
    source_account_id: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SeriesPage:
    window = checked_window(due_from, due_to)
    if (source == 'account') != bool(source_account_id):
        raise refuse(422, 'task_source_invalid', 'Wähle ein Konto oder einen anderen Quellenfilter.')
    async with get_session_maker()() as session:
        rows = await task_series.list_page(session, scope='app', due_from=due_from.isoformat(),
            due_to=(due_to + timedelta(days=1)).isoformat(), archived=None if status is None else status == 'archived',
            source=source, source_account_id=source_account_id, after=cursor, limit=limit + 1)
        items = [await series_out(session, row, due_from, due_to) for row in rows[:limit]]
        return SeriesPage(window=window, items=items, next_cursor=rows[limit - 1].id if len(rows) > limit else None)


@router.post('', operation_id='tasks_create', summary='Create a personal task')
async def create_task(body: TaskCreate) -> TaskCreated:
    try:
        # ISO 8601 allows a lowercase separator; a date has neither.
        start = datetime.fromisoformat(body.start) if 't' in body.start.lower() else date.fromisoformat(body.start)
        if not body.timezone:
            raise ValueError('timezone required')
        expand_page(start, body.rrule or 'FREQ=DAILY;COUNT=1', start, body.timezone, limit=1)
        async with get_session_maker()() as session:
            row, created = await create.create(
                session, creation_key=body.creation_key, title=body.title, description=body.description,
                start=start, zone=body.timezone, rule=body.rrule,
                source_account_id=body.source_account_id, source_message_id=body.source_message_id,
            )
            if created:
                revision = await task_schedule_revision.get_by_version(session, row.id, 1)
                if revision is None:
                    raise RuntimeError('new task revision is missing')
                await reconcile.reconcile_batch(session, scope='app', series_id=row.id,
                    revision_id=revision.id, started_at=datetime.now(UTC), cursor=None)
            await session.commit()
            return TaskCreated(id=row.id, version=row.version, created=created)
    except create.CreationConflict:
        raise refuse(409, 'task_creation_conflict', 'Diese Erstellungskennung gehört zu einer anderen Aufgabe.') from None
    except ValueError:
        raise refuse(422, 'task_invalid', 'Die Aufgabe konnte nicht angelegt werden. Prüfe ihre Angaben.') from None
