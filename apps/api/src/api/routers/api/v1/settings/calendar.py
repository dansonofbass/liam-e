"""Owner-managed default calendar for new appointments proposed in chat."""
from db.accessors import calendar_settings
from db.accessors.prompt_template import StaleVersion
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from api.errors import quiet_validation_route, refuse

router = APIRouter(route_class=quiet_validation_route("calendar_settings_invalid", "Prüfe die Kalenderauswahl."))


class CalendarSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    default_source_id: str | None


class CalendarSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    default_source_id: str | None


@router.get("", operation_id="calendar_settings_get")
async def get_calendar_settings() -> CalendarSettingsOut:
    return CalendarSettingsOut.model_validate(await calendar_settings.get())


@router.patch("", operation_id="calendar_settings_update")
async def update_calendar_settings(body: CalendarSettingsUpdate) -> CalendarSettingsOut:
    try:
        result = await calendar_settings.update(body.expected_version, body.default_source_id)
    except StaleVersion:
        raise refuse(409, "version_conflict", "Der Standardkalender wurde inzwischen geändert. Lade die Einstellungen erneut.") from None
    except calendar_settings.CalendarNotWritable:
        raise refuse(422, "calendar_settings_invalid", "Wähle einen verbundenen Kalender mit Schreibzugriff.") from None
    return CalendarSettingsOut.model_validate(result)
