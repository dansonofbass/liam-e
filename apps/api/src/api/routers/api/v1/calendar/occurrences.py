"""Read active-source calendar instances from the local index."""

import base64
import binascii
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from db.accessors import calendar_occurrence, calendar_source
from fastapi import APIRouter, HTTPException, Query

from api.routers.api.v1.calendar.schemas import OccurrenceOut, OccurrencePage

router = APIRouter()


def _decode(cursor: str) -> str:
    try:
        decoded = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode("ascii")
        if str(UUID(decoded)) != decoded:
            raise ValueError("invalid id")
        return decoded
    except (ValueError, UnicodeError, binascii.Error):
        raise HTTPException(422, "cursor_invalid") from None


def _out(row) -> OccurrenceOut:
    return OccurrenceOut.model_validate(row, from_attributes=True)


@router.get("", operation_id="calendar_occurrences_list")
async def occurrences(
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    source_id: str | None = None,
    cursor: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> OccurrencePage:
    if to_date <= from_date or to_date - from_date > timedelta(days=90):
        raise HTTPException(422, "window_invalid")
    after = _decode(cursor) if cursor else None
    if source_id:
        source = await calendar_source.get(source_id)
        if source is None or not source.is_active:
            raise HTTPException(404, "source_not_found")
    rows = await calendar_occurrence.page_visible(
        start=datetime.combine(from_date, time.min, tzinfo=UTC), end=datetime.combine(to_date, time.min, tzinfo=UTC),
        start_date=from_date, end_date=to_date, source_id=source_id, after=after, limit=limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = base64.urlsafe_b64encode(rows[-1].id.encode()).decode().rstrip("=") if more else None
    return OccurrencePage(items=[_out(row) for row in rows], next_cursor=next_cursor)


@router.get("/{occurrence_id}", operation_id="calendar_occurrence_get")
async def occurrence(occurrence_id: str) -> OccurrenceOut:
    row = await calendar_occurrence.get_visible(occurrence_id)
    if row is None:
        raise HTTPException(404, "occurrence_not_found")
    return _out(row)
