"""Owner-initiated calendar writes with durable claims and read-only reconciliation.

No provider call holds an open database transaction. Ambiguous delivery is persisted and
never retried. Connector revision checks are best effort, not provider-side compare-and-swap.
"""

import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.accessors import calendar_index_write, calendar_occurrence, calendar_source, calendar_write, calendar_sync_state
from db.models.calendar_event import CalendarEvent
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_write import CalendarWrite

from api.calendar import google, google_write
from api.calendar.seed_ids import SEED_CALENDAR_IDS
from api.mail.sync_types import html_to_text

logger = logging.getLogger(__name__)

# Builder's call: an all-day span longer than a year is almost certainly a mistake.
MAX_ALL_DAY_DAYS = 366
# A create check concludes "not applied" only after this settle time since dispatch: the
# connector may keep working after the client timeout, and provider listings may lag.
CREATE_SETTLE = timedelta(minutes=5)


class WriteError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def resolve_local(value: str, zone: str) -> datetime:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
            raise ValueError()
        naive = datetime.fromisoformat(value)
        result = naive.replace(tzinfo=ZoneInfo(zone), fold=0)
        if result.astimezone(UTC).astimezone(result.tzinfo).replace(tzinfo=None) != naive:
            raise ValueError()
        return result
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise WriteError("calendar_time_invalid", 422) from None


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    write_id: UUID
    operation: Literal["create", "update", "delete"]
    source_id: str
    occurrence_id: str | None = None
    expected_revision: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    start_local: str | None = None
    end_local: str | None = None
    timezone: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def validate_values(self):
        timed = self.start_local is not None or self.end_local is not None
        dated = self.start_date is not None or self.end_date is not None
        if timed and dated:
            raise WriteError("calendar_time_invalid", 422)
        if timed:
            if not self.start_local or not self.end_local or not self.timezone:
                raise WriteError("calendar_time_invalid", 422)
            start, end = resolve_local(self.start_local, self.timezone), resolve_local(self.end_local, self.timezone)
            duration = end.astimezone(UTC) - start.astimezone(UTC)
            if not timedelta() < duration <= timedelta(days=14):
                raise WriteError("calendar_time_invalid", 422)
        elif self.timezone is not None:
            raise WriteError("calendar_time_invalid", 422)
        if dated and (self.start_date is None or self.end_date is None or self.end_date <= self.start_date
                      or (self.end_date - self.start_date).days > MAX_ALL_DAY_DAYS):
            raise WriteError("calendar_time_invalid", 422)
        if self.operation == "create":
            if not self.title or not self.title.strip() or not (timed or dated) or self.occurrence_id is not None:
                raise WriteError("calendar_time_invalid", 422)
        elif not self.occurrence_id or not self.expected_revision:
            raise WriteError("calendar_event_gone", 422)
        fields = {k for k in ("title", "location", "description", "start_local", "start_date") if getattr(self, k) is not None}
        if self.operation == "update" and not fields:
            raise WriteError("calendar_time_invalid", 422)
        if self.operation == "delete" and (fields or timed or dated):
            raise WriteError("calendar_time_invalid", 422)
        return self


class LiveEvent(BaseModel):
    occurrence_id: str | None = None
    source_id: str
    title: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = None
    description: str | None = None
    description_was_html: bool = False
    html_link: str | None = None
    revision: str | None = None
    editable: bool = False
    reason: str | None = None


class WriteOutcome(BaseModel):
    write_id: str
    status: Literal["done", "failed", "unknown", "not_applied", "running"]
    error_code: str | None = None
    occurrence_id: str | None = None
    revision: str | None = None
    current: LiveEvent | None = None


def _out(row: CalendarWrite, *, current=None, occurrence_id=None) -> WriteOutcome:
    return WriteOutcome(write_id=row.id, status=row.status, error_code=row.error_code,
                        revision=row.result_revision, current=current, occurrence_id=occurrence_id)


async def _source(source_id: str, *, writable=True):
    source = await calendar_source.get(source_id)
    if source is None or not source.is_active:
        raise WriteError("calendar_unavailable", 404)
    if writable and (source.provider != "google" or "write" not in json.loads(source.capabilities_json)):
        raise WriteError("calendar_not_writable", 403)
    return source


async def _identity(source):
    if await google.identity() != source.connection_ref:
        raise WriteError("reconnect_required")


def _live(raw, source, occurrence_id=None):
    row = google.map_event(raw, None, source.timezone)
    allowed, reason = google.editable(raw)
    if "write" not in json.loads(source.capabilities_json):
        allowed, reason = False, "calendar_not_writable"
    description = raw.get("description")
    return LiveEvent(occurrence_id=occurrence_id, source_id=source.id, title=row.title,
        start_at=row.start_at, end_at=row.end_at, start_date=row.start_date, end_date=row.end_date,
        timezone=row.timezone, location=raw.get("location"), description=html_to_text(description) if description else None,
        description_was_html=bool(description and re.search(r"<[^>]+>", description)),
        html_link=raw.get("htmlLink"), revision=raw.get("updated"), editable=allowed, reason=reason)


async def live(occurrence_id: str) -> LiveEvent:
    row = await calendar_occurrence.get_visible(occurrence_id)
    if row is None:
        raise WriteError("calendar_event_gone", 404)
    source = await _source(row.source_id, writable=False)
    if source.id in SEED_CALENDAR_IDS and source.provider == "google":
        return _live(await _seed_raw(row), source, row.id)
    if source.provider != "google" or source.id in SEED_CALENDAR_IDS:
        return LiveEvent(occurrence_id=row.id, source_id=source.id, title=row.title,
            start_at=row.start_at, end_at=row.end_at, start_date=row.start_date, end_date=row.end_date,
            timezone=row.timezone, editable=False, reason="calendar_not_writable")
    try:
        await _identity(source)
        result = await google_write.call("get_event", {"calendarId": source.external_id, "eventId": row.external_id})
        if result.kind != "event":
            raise WriteError("calendar_event_gone" if result.status == 404 else "calendar_unavailable", 404 if result.status == 404 else 503)
        current_source = await _source(source.id, writable=False)
        if current_source.revision != source.revision or current_source.connection_ref != source.connection_ref:
            raise WriteError("calendar_unavailable", 409)
        return _live(result.event, current_source, row.id)
    except google.GoogleError:
        raise WriteError("calendar_unavailable", 503) from None


def _arguments(request: WriteRequest) -> dict:
    args = {"notificationLevel": "NONE"}
    for field, key in (("title", "summary"), ("location", "location"), ("description", "description")):
        if getattr(request, field) is not None:
            args[key] = getattr(request, field)
    if request.start_date is not None:
        args.update(allDay=True, startTime=f"{request.start_date}T00:00:00Z", endTime=f"{request.end_date}T00:00:00Z")
    elif request.start_local is not None:
        args.update(startTime=resolve_local(request.start_local, request.timezone).isoformat(),
                    endTime=resolve_local(request.end_local, request.timezone).isoformat(), timeZone=request.timezone)
        if request.operation == "update": args["allDay"] = False
    return args


def _create_match_args(args: dict) -> dict:
    return {key: value for key, value in args.items() if key in {"summary", "startTime", "endTime", "allDay"}}


def _matches(raw: dict, args: dict) -> bool:
    """Compare only explicitly changed values, treating provider null as a cleared field."""
    try:
        for key in ("summary", "location", "description"):
            if key in args and (raw.get(key) or "") != args[key]: return False
        if "startTime" in args:
            if args.get("allDay"):
                if any(raw[name].get("date") != args[key][:10] for name, key in (("start", "startTime"), ("end", "endTime"))): return False
            elif any(google.instant(raw[name]["dateTime"]) != google.instant(args[key]) for name, key in (("start", "startTime"), ("end", "endTime"))):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


async def _seed_raw(row):
    metadata = json.loads(await calendar_index_write.event_metadata(row.event_id))
    raw = metadata.get("seed_event", {})
    return {**raw, "id": row.external_id, "summary": row.title, "updated": raw.get("updated", "seed-0"),
        "start": {"date": str(row.start_date)} if row.start_date else {"dateTime": row.start_at.isoformat()},
        "end": {"date": str(row.end_date)} if row.end_date else {"dateTime": row.end_at.isoformat()}}


async def _seed_execute(record, request, source, target):
    raw = await _seed_raw(target) if target else {"id": f"seed-{record.id}"}
    if target and raw["updated"] != request.expected_revision:
        current = _live(raw, source, target.id)
        return _out(await calendar_write.finish(record.id, status="not_applied", error_code="calendar_event_changed"), current=current)
    args = _arguments(request)
    for field in ("summary", "location", "description"):
        if field in args: raw[field] = args[field]
    if "startTime" in args:
        for field, key in (("start", "startTime"), ("end", "endTime")):
            raw[field] = {"date": args[key][:10]} if args.get("allDay") else {"dateTime": args[key], "timeZone": request.timezone}
    state = await calendar_sync_state.get(source.id)
    raw["updated"] = f"seed-{(state.data_revision if state else 0) + 1}"
    return await _done(record, source, raw, source.revision)


async def _done(record, source, raw, revision):
    upsert = None
    target = record.target_external_id
    if record.operation != "delete":
        row = google.map_event(raw, None, source.timezone)
        event = CalendarEvent(source_id=source.id, external_id=row.event_external_id, title=row.title,
            recurrence_json=json.dumps({"seed_event": raw}) if source.id in SEED_CALENDAR_IDS else "{}")
        occurrence = CalendarOccurrence(source_id=source.id, event_id=event.id, **{
            k: v for k, v in vars(row).items() if k != "event_external_id"})
        upsert = event, occurrence
        target = None
    # A stale result may finish its write record, but cannot replace a newer source generation.
    await calendar_index_write.apply(source_id=source.id, upsert=upsert, delete_external_id=target,
                                     expected_revision=revision)
    result = await calendar_write.finish(record.id, status="done", result_external_id=raw.get("id") or target,
                                         result_revision=raw.get("updated"))
    stored = await calendar_index_write.find(source.id, result.result_external_id) if result.result_external_id else None
    return _out(result, occurrence_id=stored.id if stored else None)


async def execute(request: WriteRequest, *, write_id: str | None = None) -> WriteOutcome:
    # Revalidate even model_copy callers; only the service builds provider arguments.
    request = WriteRequest.model_validate(request.model_dump())
    payload = request.model_dump(mode="json", exclude={"write_id"}, exclude_none=True)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    source = await _source(request.source_id)
    identifier = write_id or str(request.write_id)
    existing = await calendar_write.get(identifier)
    if existing is not None:
        if existing.request_hash != digest: raise WriteError("calendar_write_conflict")
        return await get(identifier)
    target = None
    if request.operation != "create":
        target = await calendar_occurrence.get_visible(request.occurrence_id)
        if target is None or target.source_id != source.id:
            raise WriteError("calendar_event_gone", 404)
    bound = dict(request=request.model_dump(mode="json"), connection_ref=source.connection_ref,
                 source_revision=source.revision, proposal=write_id is not None)
    record = CalendarWrite(id=identifier, source_id=source.id, operation=request.operation,
        target_external_id=target.external_id if target else None, request_json=json.dumps(bound), request_hash=digest,
        expected_revision=request.expected_revision)
    try:
        record, claimed = await calendar_write.claim(record)
    except calendar_write.WriteConflict:
        raise WriteError("calendar_write_conflict") from None
    except calendar_write.WriteInProgress:
        raise WriteError("calendar_write_in_progress") from None
    if not claimed: return await get(identifier)
    if source.id in SEED_CALENDAR_IDS:
        try:
            return await _seed_execute(record, request, source, target)
        except Exception as error:
            # Seed writes never reach a provider, so a failure is definite and the claim must end.
            logger.warning("calendar_seed_write_failed %s", type(error).__name__)
            return _out(await calendar_write.finish(identifier, status="failed", error_code="calendar_unavailable"))
    dispatched = False
    try:
        await _identity(source)
        current_source = await _source(source.id)
        if current_source.revision != source.revision or current_source.connection_ref != source.connection_ref:
            raise WriteError("calendar_unavailable")
        args = {**_arguments(request), "calendarId": source.external_id}
        if target:
            args["eventId"] = target.external_id
            result = await google_write.call("get_event", {"calendarId": source.external_id, "eventId": target.external_id})
            if result.kind != "event":
                raise WriteError("calendar_event_gone" if result.status == 404 else "calendar_unavailable")
            if not google.editable(result.event)[0]: raise WriteError("calendar_event_not_editable")
            if result.event.get("updated") != request.expected_revision:
                current = _live(result.event, source, target.id)
                record = await calendar_write.finish(identifier, status="not_applied", error_code="calendar_event_changed")
                return _out(record, current=current)
        current_source = await _source(source.id)
        if current_source.revision != source.revision or current_source.connection_ref != source.connection_ref:
            raise WriteError("calendar_unavailable")
        if not await calendar_write.mark_dispatch(identifier):
            # A concurrent read expired the claim while we prepared; it may already have been
            # reconciled as not applied, so sending now could contradict the stored outcome.
            return await get(identifier)
        dispatched = True
        result = await google_write.call(f"{request.operation}_event", args)
        if result.kind == "event" and (request.operation != "create" or _matches(result.event, _create_match_args(args))):
            if target and result.event["id"] != target.external_id:
                result = google_write.ToolResult("unknown")
            else:
                return await _done(record, source, result.event, source.revision)
        if result.kind == "failed":
            code = "calendar_write_rejected"
            if result.status == 404: code = "calendar_unavailable" if request.operation == "create" else "calendar_event_gone"
            return _out(await calendar_write.finish(identifier, status="failed", error_code=code))
    except (WriteError, google.GoogleError) as error:
        if not dispatched:
            code = error.code if isinstance(error, WriteError) else "calendar_unavailable"
            return _out(await calendar_write.finish(identifier, status="failed", error_code=code))
    except Exception as error:
        # Class name only: transport/provider exceptions may contain private values.
        logger.warning("calendar_write_unexpected %s", type(error).__name__)
    return _out(await calendar_write.finish(identifier, status="unknown", error_code="calendar_write_unknown"))


async def get(write_id: str) -> WriteOutcome:
    row = await calendar_write.expire_running(write_id, before=datetime.now(UTC) - timedelta(seconds=120))
    if row is None: raise WriteError("calendar_unavailable", 404)
    if row.status == "unknown" and row.request_json:
        return await check(write_id)
    stored = await calendar_index_write.find(row.source_id, row.result_external_id) if row.result_external_id else None
    return _out(row, occurrence_id=stored.id if stored else None)


async def _checked(record, bound, outcome):
    if bound.get("proposal"):
        from api.mail import proposals
        try:
            message = await proposals._get_proposal(record.id)
            proposal = proposals.proposal_view(message)
            # "running" covers a card whose confirm call died after claiming it.
            if proposal and proposal.kind == "calendar" and message.proposal_status in {"unknown", "running"}:
                await proposals._store_calendar(message, proposal, outcome)
        except proposals.ProposalNotFoundError:
            pass
    return outcome


async def check(write_id: str) -> WriteOutcome:
    record = await calendar_write.expire_running(write_id, before=datetime.now(UTC) - timedelta(seconds=120))
    if record is None: raise WriteError("calendar_unavailable", 404)
    if record.status != "unknown" or not record.request_json: return _out(record)
    try:
        source = await _source(record.source_id)
        if source.id in SEED_CALENDAR_IDS:
            return _out(record)
        bound = json.loads(record.request_json)
        if source.connection_ref != bound["connection_ref"]:
            return _out(record)
        await _identity(source)
        request = WriteRequest.model_validate(bound["request"])
        args = _arguments(request)
        raw = None
        not_applied = False
        if record.operation == "create":
            start = google.instant(args["startTime"])
            end = google.instant(args["endTime"])
            # No free-text filter: its tokenisation could hide the event and fake "not applied".
            pages = await google.pages(google.live_call, "list_events", {
                "calendarId": source.external_id, "startTime": (start - timedelta(minutes=1)).isoformat(),
                "endTime": (end + timedelta(minutes=1)).isoformat(), "pageSize": 250})
            recent, matches = [], []
            for page in pages:
                for candidate in page["events"]:
                    if not (isinstance(candidate.get("id"), str) and candidate["id"] and candidate.get("status") != "cancelled"):
                        continue
                    try:
                        fresh = google.instant(candidate.get("created")) >= record.started_at - timedelta(minutes=5)
                    except (TypeError, ValueError):
                        fresh = True  # Unknown creation time: treat as possibly ours.
                    if fresh:
                        recent.append(candidate)
                        if _matches(candidate, _create_match_args(args)):
                            matches.append(candidate)
            if len(matches) == 1: raw = matches[0]
            # Any event created in the window since the claim (even renamed) keeps the outcome
            # open, and so does a write that has not had time to settle at the provider.
            not_applied = not recent and datetime.now(UTC) - record.started_at >= CREATE_SETTLE
        else:
            result = await google_write.call("get_event", {"calendarId": source.external_id, "eventId": record.target_external_id})
            if record.operation == "delete" and result.status == 404:
                # A 404 also answers for a calendar that was deleted or unshared: only a
                # reachable calendar makes the missing event a completed delete.
                page = await google.live_call("list_events", {
                    "calendarId": source.external_id, "startTime": datetime.now(UTC).isoformat(),
                    "endTime": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(), "pageSize": 1})
                if not isinstance(page, dict) or not isinstance(page.get("events"), list):
                    raise google.GoogleError()
                raw = {"id": record.target_external_id}
            elif result.kind == "event" and result.event["id"] == record.target_external_id:
                candidate = result.event
                if record.operation == "delete":
                    if candidate.get("status") == "cancelled": raw = candidate
                elif candidate.get("status") != "cancelled" and _matches(candidate, args): raw = candidate
                not_applied = raw is None and candidate.get("updated") == record.expected_revision
        # Reconciliation must not associate a result from a newly connected account.
        await _identity(source)
        if raw is not None:
            return await _checked(record, bound, await _done(record, source, raw, bound["source_revision"]))
        if not_applied:
            result = _out(await calendar_write.finish(record.id, status="not_applied", error_code="calendar_write_not_applied"))
            return await _checked(record, bound, result)
    except Exception as error:
        # The record stays unknown; class name only, never provider text.
        logger.warning("calendar_write_check_failed %s", type(error).__name__)
    return _out(record)
