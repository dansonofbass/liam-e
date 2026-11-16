"""Create personal task series."""

from datetime import date, datetime

from db.engine import get_session_maker
from fastapi import APIRouter

from api.errors import refuse
from api.tasks import create
from .schemas import TaskCreate, TaskCreated

router = APIRouter()


@router.post('', operation_id='tasks_create', summary='Create a personal task')
async def create_task(body: TaskCreate) -> TaskCreated:
    try:
        start = datetime.fromisoformat(body.start) if 'T' in body.start else date.fromisoformat(body.start)
        async with get_session_maker()() as session:
            row, created = await create.create(
                session, creation_key=body.creation_key, title=body.title, description=body.description,
                start=start, zone=body.timezone, rule=body.rrule,
                source_account_id=body.source_account_id, source_message_id=body.source_message_id,
            )
            await session.commit()
            return TaskCreated(id=row.id, version=row.version, created=created)
    except create.CreationConflict:
        raise refuse(409, 'task_creation_conflict', 'Diese Erstellungskennung gehört zu einer anderen Aufgabe.') from None
    except ValueError:
        raise refuse(422, 'task_invalid', 'Die Aufgabe konnte nicht angelegt werden. Prüfe ihre Angaben.') from None
