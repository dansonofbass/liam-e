"""Inspect uncertain writes without repeating a mutation."""

from fastapi import APIRouter, Response

from api.calendar import writes
from api.routers.api.v1.calendar import _writes

router = APIRouter(route_class=_writes.QuietWriteRoute)


@router.get("/{write_id}", operation_id="calendar_write_get")
async def get(write_id: str, response: Response) -> writes.WriteOutcome:
    try:
        return _writes.outcome(await writes.get(write_id), response)
    except writes.WriteError as exc:
        raise _writes.error(exc) from None


@router.post("/{write_id}/check", operation_id="calendar_write_check")
async def check(write_id: str, response: Response) -> writes.WriteOutcome:
    try:
        return _writes.outcome(await writes.check(write_id), response)
    except writes.WriteError as exc:
        raise _writes.error(exc) from None
