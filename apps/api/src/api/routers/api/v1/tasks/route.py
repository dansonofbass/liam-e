"""Create personal task series."""

from datetime import UTC, date, datetime

from db.accessors import task_schedule_revision
from db.engine import get_session_maker
from fastapi import APIRouter

from api.errors import refuse
from api.tasks import create, reconcile
from api.tasks.recurrence import expand_page
from .schemas import TaskCreate, TaskCreated

router = APIRouter()


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
