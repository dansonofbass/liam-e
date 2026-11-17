"""Read-only schedule preview with explanations for skipped calendar values."""

from datetime import date, datetime

from fastapi import APIRouter

from api.errors import refuse
from api.tasks.preview import preview
from .schemas import PreviewIn, PreviewOut

router = APIRouter()


@router.post('', operation_id='tasks_preview', summary='Preview a task schedule without writes')
async def preview_task(body: PreviewIn) -> PreviewOut:
    try:
        parse = datetime.fromisoformat if 'T' in body.start.upper() else date.fromisoformat
        return PreviewOut(**preview(parse(body.start), body.rrule, parse(body.through), body.timezone, limit=body.limit))
    except (ValueError, TypeError, OverflowError):
        raise refuse(422, 'task_invalid', 'Die Vorschau konnte nicht erstellt werden. Prüfe den Zeitraum und die Wiederholung.') from None
