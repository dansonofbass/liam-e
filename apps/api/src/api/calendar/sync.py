"""Calendar snapshot dispatch through the durable technical job queue."""

import json
from datetime import UTC, datetime

from db.accessors import calendar_source, mail_job
from db.accessors.calendar_snapshot import replace_window
from db.models.calendar_event import CalendarEvent
from db.models.calendar_occurrence import CalendarOccurrence

from api.calendar.adapters import Adapter, normalize, timed_overlaps
from api.calendar.seed_ids import SEED_CALENDAR_IDS

_adapters: dict[str, Adapter] = {}


def register_adapter(provider: str, adapter: Adapter) -> None:
    _adapters[provider] = adapter


def register_worker() -> None:
    from api.mail.jobs import register_claim_handler
    from api.calendar.feed_jobs import StoredICSAdapter
    from api.calendar.google import GoogleConnectorAdapter
    register_adapter("ics", StoredICSAdapter())
    register_adapter("google", GoogleConnectorAdapter())
    register_claim_handler("calendar_sync", run_sync)


async def enqueue(source_id: str, start: datetime, end: datetime) -> bool:
    if (start.tzinfo is None or end.tzinfo is None or start.utcoffset() is None or end.utcoffset() is None
            or start >= end):
        raise ValueError("invalid window")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if any((start.hour, start.minute, start.second, start.microsecond, end.hour, end.minute, end.second, end.microsecond)):
        raise ValueError("window must use UTC date boundaries")
    if source_id in SEED_CALENDAR_IDS:
        return False
    source = await calendar_source.get(source_id)
    if source is not None and source.provider in {"ics", "google"}:
        from api.calendar.feed_jobs import enqueue as enqueue_feed
        return await enqueue_feed(source_id, manual=True)
    payload = {"source_id": source_id, "start": start.isoformat(), "end": end.isoformat()}
    return await mail_job.enqueue("calendar_sync", payload, dedupe_key=f"calendar_sync:{source_id}") is not None


async def run_sync(payload: dict, job_id: str, attempt: int) -> None:
    if payload["source_id"] in SEED_CALENDAR_IDS:
        return
    source = await calendar_source.get(payload["source_id"])
    if source is None or not source.is_active:
        raise LookupError("source unavailable")
    adapter = _adapters.get(source.provider)
    if adapter is None:
        raise LookupError("adapter unavailable")
    if source.provider in {"ics", "google"}:
        from api.calendar.ics import default_window
        start, end = default_window()
    else:
        start, end = datetime.fromisoformat(payload["start"]), datetime.fromisoformat(payload["end"])
    snapshot = await adapter.snapshot(source.id, start, end)
    if source.provider in {"ics", "google"} and snapshot.source_revision != source.revision:
        raise LookupError("source_changed")
    if not snapshot.complete:
        raise ValueError("incomplete snapshot")
    if len(snapshot.events) > 10000 or len(snapshot.occurrences) > 50000:
        raise ValueError("snapshot limit")
    events = [CalendarEvent(source_id=source.id, external_id=e.external_id, title=e.title,
                            recurrence_json=json.dumps(e.recurrence, ensure_ascii=False)) for e in snapshot.events]
    ids = {e.external_id: e.id for e in events}
    if len(ids) != len(events):
        raise ValueError("duplicate event")
    occurrences = []
    for raw in snapshot.occurrences:
        row = normalize(raw)
        if row.event_external_id not in ids or not row.external_id:
            raise ValueError("unknown event or empty identity")
        if row.start_date is not None:
            in_window = row.start_date < end.date() and row.end_date > start.date()
        else:
            in_window = timed_overlaps(row.start_at, row.end_at, start, end)
        if not in_window:
            raise ValueError("occurrence outside window")
        occurrences.append(CalendarOccurrence(source_id=source.id, event_id=ids[row.event_external_id],
                                               external_id=row.external_id, title=row.title, editable=row.editable,
                                               start_date=row.start_date, end_date=row.end_date,
                                               start_at=row.start_at, end_at=row.end_at, timezone=row.timezone))
    await replace_window(source_id=source.id, job_id=job_id, attempt=attempt, start=start, end=end,
                         start_date=start.date(), end_date=end.date(), events=events, occurrences=occurrences,
                         expected_revision=source.revision,
                         replace_all=source.provider in {"ics", "google"},
                         reset_schedule=source.provider in {"ics", "google"},
                         encrypted_validators=getattr(snapshot, "encrypted_validators", None),
                         capabilities_json=(('["read","write"]' if snapshot.access_role in {"owner", "writer"} else '["read"]')
                                            if source.provider == "google" else None))
