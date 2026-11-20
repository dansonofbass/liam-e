"""The temporary owner device check validates recordings and serves a bundled speech sample."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from env.audio import env
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from api.audio import recording
from api.audio.capabilities import TRANSCRIPTION_APP_LIMITS, TranscriptionLimitsOut
from api.audio.errors import NO_STORE, audio_error

_WEBM: Literal["audio/webm;codecs=opus"] = "audio/webm;codecs=opus"
_SAMPLE_TEXT = "Eine gelbe Ente schwimmt im Teich."
_SAMPLE_FILE = Path(recording.__file__).with_name("device-sample.mp3")


def active_device_test() -> datetime:
    try:
        expires = datetime.fromisoformat(env.audio_device_test_until or "")
        now = datetime.now(timezone.utc)
        if expires.utcoffset() is not None and now < expires <= now + timedelta(days=3):
            return expires
    except ValueError:
        pass
    raise HTTPException(404, detail="audio_device_test_closed", headers=NO_STORE)


router = APIRouter(dependencies=[Depends(active_device_test)])


class DeviceTestOut(BaseModel):
    expires_at: datetime
    sample_text: str
    format: Literal["audio/webm;codecs=opus"]
    app_limits: TranscriptionLimitsOut


class DeviceRecordingOut(BaseModel):
    request_id: UUID
    text: str


@router.get("", operation_id="audio_device_test_get")
async def status(response: Response, expires_at: Annotated[datetime, Depends(active_device_test)]) -> DeviceTestOut:
    response.headers.update(NO_STORE)
    return DeviceTestOut(expires_at=expires_at, sample_text=_SAMPLE_TEXT, format=_WEBM, app_limits=TRANSCRIPTION_APP_LIMITS)


@router.post(
    "/recording", operation_id="audio_device_test_record",
    openapi_extra={"requestBody": recording.RECORDING_REQUEST_BODY},
)
async def validate(
    request: Request, response: Response,
    slot: Annotated[recording.Slot, Depends(recording.get_transcription_slot)],
) -> DeviceRecordingOut:
    try:
        async with slot() as acquired:
            if not acquired:
                raise audio_error("audio_rate_limited")
            async with recording.validated_recording(request, (_WEBM,)) as (_, _, request_id, _):
                active_device_test()
                response.headers.update(NO_STORE)
                return DeviceRecordingOut(request_id=request_id, text=_SAMPLE_TEXT)
    except (SQLAlchemyError, OSError):
        raise audio_error("audio_unavailable") from None


@router.get(
    "/sample", operation_id="audio_device_test_sample", response_class=Response,
    responses={200: {"content": {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}}}},
)
def sample() -> Response:
    return Response(_SAMPLE_FILE.read_bytes(), media_type="audio/mpeg", headers=NO_STORE)
