"""Manage local calendar source selection and refresh jobs."""

from datetime import UTC, datetime, time, timedelta

from db.accessors import calendar_source, calendar_sync_state
from fastapi import APIRouter, HTTPException, Response

from api.calendar import sync
from api.routers.api.v1.calendar.schemas import SourceOut, SourcePatch, SyncOut

router = APIRouter()


async def source_out(source) -> SourceOut:
    return source_status(source, await calendar_sync_state.get(source.id))


def source_status(source, state) -> SourceOut:
    last = state.last_success_at if state else None
    return SourceOut(id=source.id, provider=source.provider, name=source.name, timezone=source.timezone,
                     is_active=source.is_active, capabilities=calendar_source.capabilities(source),
                     chat_access=calendar_source.chat_access(source, state),
                     coverage_start=state.coverage_start if state else None,
                     coverage_end=state.coverage_end if state else None, last_success_at=last,
                     stale=last is None or state.incomplete,
                     incomplete=state.incomplete if state else True,
                     revision=source.revision,
                     last_checked_at=state.last_checked_at if state else None,
                     last_validated_at=state.last_validated_at if state else None,
                     last_error=state.last_error if state else None,
                     data_revision=state.data_revision if state else 0)


@router.get("", operation_id="calendar_sources_list")
async def sources() -> list[SourceOut]:
    return [source_status(source, state) for source, state in await calendar_source.catalog()]


@router.patch("/{source_id}", operation_id="calendar_source_update")
async def update(source_id: str, body: SourcePatch) -> SourceOut:
    row = await calendar_source.set_active(source_id, body.is_active)
    if row is None:
        raise HTTPException(404, "source_not_found")
    if row.provider in {"ics", "google"} and row.is_active:
        from api.calendar.feed_jobs import enqueue
        await enqueue(row.id, manual=True)
    return await source_out(row)


@router.delete("/{source_id}", operation_id="calendar_source_delete", status_code=204)
async def remove(source_id: str) -> Response:
    if not await calendar_source.remove(source_id):
        raise HTTPException(404, "source_not_found")
    return Response(status_code=204)


@router.post("/{source_id}/sync", operation_id="calendar_source_sync")
async def refresh(source_id: str, due_only: bool = False) -> SyncOut:
    source = await calendar_source.get(source_id)
    if source is None or not source.is_active:
        raise HTTPException(404, "source_not_found")
    if source.provider in {"ics", "google"}:
        from api.calendar.feed_jobs import enqueue
        return SyncOut(queued=await enqueue(source_id, manual=not due_only))
    today = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return SyncOut(queued=await sync.enqueue(source_id, today - timedelta(days=30), today + timedelta(days=60)))
