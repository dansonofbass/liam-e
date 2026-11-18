"""Discover and connect read-only Studio calendars; never accept connection identities."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from db.accessors import calendar_source
from env.calendar import env
from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import JSONResponse

from api.calendar import google
from api.routers.api.v1.calendar.schemas import SourceOut
from api.routers.api.v1.calendar.sources import source_out


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse({"detail": "calendar_invalid"}, status_code=422)
            except HTTPException as error:
                response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
            response.headers["Cache-Control"] = "no-store"
            return response
        return private_handler


router = APIRouter(route_class=PrivateRoute)


class GoogleCalendarOut(BaseModel):
    id: str
    name: str
    timezone: str
    access: Literal["owner", "reader"] | None
    source_id: str | None


class GoogleCalendarsOut(BaseModel):
    calendars: list[GoogleCalendarOut]


class GoogleConnectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendar_ids: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(min_length=1, max_length=20, repr=False)

    @field_validator("calendar_ids")
    @classmethod
    def unique(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("calendar_invalid")
        return values


async def discover():
    try:
        return await google.calendars()
    except google.GoogleError as error:
        if error.code == "reconnect_required":
            raise HTTPException(409, "google_calendar_not_connected") from None
        raise HTTPException(502, "provider_unavailable") from None


@router.get("/calendars", operation_id="calendar_google_calendars_list")
async def calendars() -> GoogleCalendarsOut:
    ref, listing = await discover()
    connected = {row.external_id: row.id for row in await calendar_source.list_connection("google", ref)}
    return GoogleCalendarsOut(calendars=[GoogleCalendarOut(**row, source_id=connected.get(row["id"])) for row in listing])


@router.post("", operation_id="calendar_google_connect")
async def connect(body: GoogleConnectInput) -> list[SourceOut]:
    ref, listing = await discover()
    available = {row["id"]: row for row in listing}
    if any(identifier not in available for identifier in body.calendar_ids):
        raise HTTPException(422, "calendar_unknown")
    selected = [available[identifier] for identifier in body.calendar_ids]
    rows = await calendar_source.connect_google(ref, selected, now=datetime.now(UTC),
                                               interval=env.calendar_google_sync_interval_minutes)
    return [await source_out(row) for row in rows]
