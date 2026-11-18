"""Read active-source calendar instances from the local index."""

import base64
import binascii
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from db.accessors import calendar_occurrence, calendar_source, calendar_write
from fastapi import APIRouter, HTTPException, Query, Response

from api.routers.api.v1.calendar.schemas import OccurrenceOut, OccurrencePage, EventUpdateIn, EventDeleteIn
from api.routers.api.v1.calendar import _writes
from api.calendar import writes

router = APIRouter(route_class=_writes.QuietWriteRoute)

# A selection, not a bulk export: the calendar view filters by a handful of sources at most.
MAX_SOURCE_IDS = 50


def _encode(row) -> str:
    key = calendar_occurrence.sort_key(row).isoformat()
    return base64.urlsafe_b64encode(f"{key}|{row.id}".encode()).decode().rstrip("=")


def _decode(cursor: str) -> tuple[datetime, str]:
    """The (sort key, id) of the last row of the previous page; anything else is 422."""
    try:
        decoded = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode("ascii")
        key, _, row_id = decoded.partition("|")
        if str(UUID(row_id)) != row_id:
            raise ValueError("invalid id")
        at = datetime.fromisoformat(key)
        if at.tzinfo is None:
            raise ValueError("naive cursor time")
        return at, row_id
    except (ValueError, UnicodeError, binascii.Error):
        raise HTTPException(422, "cursor_invalid") from None


def _out(row) -> OccurrenceOut:
    return OccurrenceOut.model_validate(row, from_attributes=True)


@router.get("", operation_id="calendar_occurrences_list")
async def occurrences(
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    source_ids: Annotated[list[str] | None, Query(max_length=MAX_SOURCE_IDS)] = None,
    cursor: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> OccurrencePage:
    if to_date <= from_date or to_date - from_date > timedelta(days=90):
        raise HTTPException(422, "window_invalid")
    after = _decode(cursor) if cursor else None
    wanted = list(dict.fromkeys(source_ids or []))
    for source_id in wanted:
        source = await calendar_source.get(source_id)
        if source is None or not source.is_active:
            raise HTTPException(404, "source_not_found")
    rows = await calendar_occurrence.page_visible(
        start=datetime.combine(from_date, time.min, tzinfo=UTC), end=datetime.combine(to_date, time.min, tzinfo=UTC),
        start_date=from_date, end_date=to_date, source_ids=wanted or None, after=after, limit=limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode(rows[-1]) if more else None
    return OccurrencePage(items=[_out(row) for row in rows], next_cursor=next_cursor)


@router.get("/{occurrence_id}", operation_id="calendar_occurrence_get")
async def occurrence(occurrence_id: str) -> OccurrenceOut:
    row = await calendar_occurrence.get_visible(occurrence_id)
    if row is None:
        raise HTTPException(404, "occurrence_not_found")
    return _out(row)


@router.get("/{occurrence_id}/live", operation_id="calendar_occurrence_live")
async def live(occurrence_id: str) -> writes.LiveEvent:
    try:
        return await writes.live(occurrence_id)
    except writes.WriteError as exc:
        raise _writes.error(exc) from None


async def _change(occurrence_id, body, response, operation):
    row = await calendar_occurrence.get_visible(occurrence_id)
    previous = await calendar_write.get(str(body.write_id)) if row is None else None
    if row is None and previous is None:
        raise _writes.error(writes.WriteError("calendar_event_gone", 404))
    return await _writes.execute({**body.model_dump(exclude_unset=True), "operation": operation,
        "source_id": row.source_id if row else previous.source_id, "occurrence_id": occurrence_id}, response)


@router.patch("/{occurrence_id}", operation_id="calendar_event_update")
async def update(occurrence_id: str, body: EventUpdateIn, response: Response) -> writes.WriteOutcome:
    return await _change(occurrence_id, body, response, "update")


@router.delete("/{occurrence_id}", operation_id="calendar_event_delete")
async def delete(occurrence_id: str, body: EventDeleteIn, response: Response) -> writes.WriteOutcome:
    return await _change(occurrence_id, body, response, "delete")
