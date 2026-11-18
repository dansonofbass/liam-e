"""Direct appointment creation, never exposed as an agent tool."""

from fastapi import APIRouter, Response

from api.calendar.writes import WriteOutcome
from api.routers.api.v1.calendar import _writes
from api.routers.api.v1.calendar.schemas import EventCreateIn

router = APIRouter(route_class=_writes.QuietWriteRoute)


@router.post("", operation_id="calendar_event_create", status_code=201)
async def create(body: EventCreateIn, response: Response) -> WriteOutcome:
    return await _writes.execute({**body.model_dump(exclude_unset=True), "operation": "create"}, response, created=True)
