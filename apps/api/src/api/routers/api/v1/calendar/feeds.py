"""Privileged feed setup; validation errors must not echo secret-bearing inputs."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from api.calendar import feeds
from api.routers.api.v1.calendar.schemas import SourceOut
from api.routers.api.v1.calendar.sources import source_out


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse({"detail": "calendar_feed_invalid"}, status_code=422)
            response.headers["Cache-Control"] = "no-store"
            return response
        return private_handler


router = APIRouter(route_class=PrivateRoute)


class FeedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str = Field(repr=False, min_length=1, max_length=4096)
    timezone: str = Field(min_length=1, max_length=100)
    source_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class SubscribeInput(FeedInput):
    validation_id: str = Field(repr=False, min_length=40, max_length=100)


class DiscardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_id: str = Field(repr=False, min_length=40, max_length=100)


class FeedPreviewOut(BaseModel):
    validation_id: str
    name: str
    coverage_start: datetime
    coverage_end: datetime
    occurrence_count: int
    expires_at: datetime
    format_issues: list[str]


def config(body: FeedInput):
    try:
        return feeds.configuration(**body.model_dump(exclude={"validation_id"}))
    except feeds.FeedError:
        raise HTTPException(422, "calendar_feed_invalid") from None


@router.post("/validate", operation_id="calendar_feed_validate")
async def validate(body: FeedInput) -> FeedPreviewOut:
    normalized = config(body)
    try:
        return FeedPreviewOut(**await feeds.validate(normalized))
    except feeds.FeedError:
        raise HTTPException(422, "calendar_feed_unavailable") from None


@router.post("", operation_id="calendar_feed_subscribe", status_code=201)
async def subscribe(body: SubscribeInput) -> SourceOut:
    normalized = config(body)
    try:
        source = await feeds.subscribe(body.validation_id, normalized)
    except feeds.FeedError:
        raise HTTPException(409, "calendar_validation_expired_or_changed") from None
    return await source_out(source)


@router.post("/validations/discard", operation_id="calendar_feed_validation_discard", status_code=204)
async def discard(body: DiscardInput) -> Response:
    await feeds.discard(body.validation_id)
    return Response(status_code=204)
