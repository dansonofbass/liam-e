"""Bounded explicit catch-up; no worker or read endpoint materializes tasks."""

import json

from db.engine import get_session_maker
from fastapi import APIRouter

from api.errors import refuse
from api.tasks.reconcile import ReconcileConflict, reconcile_current
from .schemas import ReconcileIn, ReconcileOut

router = APIRouter()


@router.post('', operation_id='tasks_reconcile', summary='Materialize one bounded task page')
async def reconcile(body: ReconcileIn) -> ReconcileOut:
    try:
        async with get_session_maker()() as session:
            revision, cursor, complete = await reconcile_current(
                session, series_id=body.series_id, revision_id=body.revision_id,
                cursor=body.cursor, advance=body.advance, limit=body.limit,
            )
            result = ReconcileOut(revision_id=revision, cursor=cursor,
                                  target=json.loads(cursor)['target'], complete=complete)
            await session.commit()
            return result
    except ReconcileConflict:
        raise refuse(409, 'task_reconcile_conflict', 'Der Abrufstand wurde geändert. Lade ihn noch einmal.') from None
    except (ValueError, OverflowError):
        raise refuse(422, 'task_invalid', 'Die Aufgaben konnten nicht abgerufen werden. Prüfe ihre Angaben.') from None
