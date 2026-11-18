"""Shared browser-only write response and redacted error handling."""

from fastapi import HTTPException, Response
from pydantic import ValidationError

from api.calendar import writes
from api.errors import quiet_validation_route, refuse

MESSAGE = "Der Termin konnte nicht geändert werden. Prüfe den aktuellen Stand und versuch es erneut."
QuietWriteRoute = quiet_validation_route("calendar_time_invalid", "Prüfe die Angaben zum Termin.")


def error(exc: writes.WriteError):
    return refuse(exc.status, exc.code, MESSAGE)


def outcome(value: writes.WriteOutcome, response: Response, *, created=False):
    if value.error_code == "calendar_event_changed":
        raise HTTPException(409, detail=value.model_dump(mode="json"))
    if value.status == "failed":
        code = value.error_code or "calendar_write_rejected"
        status = 404 if code in {"calendar_event_gone", "calendar_unavailable"} else 403 if code in {"calendar_not_writable", "calendar_write_rejected"} else 409
        raise HTTPException(status, detail=value.model_dump(mode="json"))
    response.status_code = 202 if value.status in {"unknown", "running"} else 201 if created and value.status == "done" else 200
    return value


async def execute(payload, response: Response, *, created=False):
    try:
        request = writes.WriteRequest.model_validate(payload)
        return outcome(await writes.execute(request), response, created=created)
    except writes.WriteError as exc:
        raise error(exc) from None
    except LookupError:
        # The source and its write records were removed while the write ran.
        raise error(writes.WriteError("calendar_unavailable", 404)) from None
    except ValidationError:
        raise refuse(422, "calendar_time_invalid", "Prüfe die Angaben zum Termin.") from None
