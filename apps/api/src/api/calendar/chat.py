"""Prepare calendar cards from scoped server reads, never execute changes."""

from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from db.accessors import calendar_occurrence, calendar_settings, calendar_source
from pydantic import ValidationError

from api.calendar import writes
from api.calendar.chat_target import mentions, named_choice, stated_destination
from api.calendar.proposals import CalendarCommand, CalendarValues, values


async def _create_source(arguments, ctx):
    named = arguments.get("calendar_name")
    source_id = arguments.get("source_id")
    if source_id and source_id not in ctx.calendar_source_ids:
        raise writes.WriteError("calendar_out_of_scope", 403)
    target = await stated_destination(ctx.user_text, ctx.calendar_source_ids)
    pending = target or ctx.requested_calendar or ctx.calendar_choice
    if named is not None:
        if not isinstance(named, str) or not named.strip():
            raise writes.WriteError("calendar_name_required", 422)
        if mentions(ctx.user_text, named):
            if target and target.name and target.name.strip().casefold() != named.strip().casefold():
                raise writes.WriteError("calendar_name_required", 422)
            pending = named_choice(named, await calendar_source.catalog(ids=ctx.calendar_source_ids))
        elif not pending or pending.name.strip().casefold() != named.strip().casefold():
            raise writes.WriteError("calendar_name_required", 422)
    if pending:
        ctx.requested_calendar = pending
        if pending.error:
            raise writes.WriteError(pending.error, 422)
        if pending.source_id not in ctx.calendar_source_ids or (source_id and source_id != pending.source_id):
            raise writes.WriteError("calendar_out_of_scope", 403)
        return pending.source_id

    default_id = (await calendar_settings.get()).default_source_id
    if source_id and source_id != default_id:
        raise writes.WriteError("calendar_name_required", 422)
    if not default_id:
        raise writes.WriteError("calendar_default_missing", 422)
    if default_id not in ctx.calendar_source_ids:
        raise writes.WriteError("calendar_default_unavailable", 409)
    return default_id


async def prepare(arguments: dict, ctx) -> CalendarCommand:
    allowed = {"action", "reason", "source_id", "calendar_name", "occurrence_id", "title", "start_local", "end_local",
               "start_date", "end_date", "timezone", "location", "description"}
    if set(arguments) - allowed:
        raise writes.WriteError("calendar_time_invalid", 422)
    action = arguments.get("action")
    source_id = arguments.get("source_id")
    occurrence_id = arguments.get("occurrence_id")
    if action == "create":
        source_id = await _create_source(arguments, ctx)
    if action in {"update", "delete"}:
        row = await calendar_occurrence.get_visible(occurrence_id or "")
        if row is None:
            raise writes.WriteError("calendar_event_gone", 404)
        if source_id and source_id != row.source_id:
            raise writes.WriteError("calendar_out_of_scope", 403)
        source_id = row.source_id
    if source_id not in ctx.calendar_source_ids:
        raise writes.WriteError("calendar_out_of_scope", 403)
    entry = await calendar_source.catalog(ids=[source_id])
    if not entry or calendar_source.chat_access(*entry[0]) != "writable":
        raise writes.WriteError("calendar_not_writable", 403)
    source, _ = entry[0]
    choice = ctx.requested_calendar
    if action == "create" and choice and source.id == choice.source_id and source.connection_ref != choice.connection_ref:
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
