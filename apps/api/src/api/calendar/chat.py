"""Prepare calendar cards from scoped server reads, never execute changes."""

import json
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from db.accessors import calendar_occurrence, calendar_source
from pydantic import ValidationError

from api.calendar import writes
from api.calendar.proposals import CalendarCommand, CalendarValues, values


async def prepare(arguments: dict, ctx) -> CalendarCommand:
    allowed = {"action", "reason", "source_id", "occurrence_id", "title", "start_local", "end_local",
               "start_date", "end_date", "timezone", "location", "description"}
    if set(arguments) - allowed:
        raise writes.WriteError("calendar_time_invalid", 422)
    action = arguments.get("action")
    source_id = arguments.get("source_id")
    occurrence_id = arguments.get("occurrence_id")
    if action in {"update", "delete"}:
        row = await calendar_occurrence.get_visible(occurrence_id or "")
        if row is None:
            raise writes.WriteError("calendar_event_gone", 404)
        if source_id and source_id != row.source_id:
            raise writes.WriteError("calendar_out_of_scope", 403)
        source_id = row.source_id
    if source_id not in ctx.calendar_source_ids:
        raise writes.WriteError("calendar_out_of_scope", 403)
    source = await calendar_source.get(source_id)
    if source is None or not source.is_active or source.provider != "google" or "write" not in json.loads(source.capabilities_json):
        raise writes.WriteError("calendar_not_writable", 403)
    before = await writes.live(occurrence_id) if action in {"update", "delete"} else None
    if before and (before.source_id != source_id or not before.editable):
        raise writes.WriteError("calendar_event_not_editable")
    if before is not None:
        # Google's htmlLink encodes event and calendar IDs; cards reach chat history and SSE.
        before = before.model_copy(update={"html_link": None})
    zone = arguments.get("timezone") or ctx.calendar_timezone
    try:
        ZoneInfo(zone)
        after = None
        if action != "delete":
            supplied = {k: v for k, v in arguments.items() if k in CalendarValues.model_fields and v is not None}
            if "start_local" in supplied or "end_local" in supplied:
                supplied.update(timezone=zone, start_date=None, end_date=None)
            elif "start_date" in supplied or "end_date" in supplied:
                supplied.update(start_local=None, end_local=None, timezone=None)
            base = values(before, zone).model_dump() if before else {}
            after = CalendarValues.model_validate({**base, **supplied})
        command = CalendarCommand(action=action, source_id=source_id, connection_ref=source.connection_ref,
            occurrence_id=occurrence_id, expected_revision=before.revision if before else None,
            timezone=zone, before=before, after=after)
        command.request(str(uuid4()))
        return command
    except (ValidationError, ValueError, TypeError, ZoneInfoNotFoundError):
        raise writes.WriteError("calendar_time_invalid", 422) from None
