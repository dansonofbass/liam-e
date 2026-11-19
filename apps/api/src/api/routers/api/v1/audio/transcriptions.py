"""Transcribe a verified owner's bounded recording after their explicit upload."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Literal
from uuid import UUID

from db.accessors.audio import transcription_slot
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from api.audio.capabilities import audio_capabilities
from api.audio.containers import MAX_BYTES, check_recording
from api.audio.errors import NO_STORE, audio_error
from api.audio.provider import MistralAudio, get_audio_provider
from api.audio.requests import bounded_body

router = APIRouter()
_UPLOAD_OVERHEAD = 16 * 1024
_UPLOAD_TIMEOUT = 20
_FORMATS = {"audio/webm;codecs=opus": "webm", "audio/mp4;codecs=mp4a.40.2": "mp4"}
_REJECTIONS = {
    "too_large": "audio_too_large",
    "too_long": "audio_too_long",
    "empty": "audio_empty",
    "invalid_container": "audio_format_unsupported",
    "timeout": "audio_timeout",
}
_REQUEST_BODY = {
    "required": True,
    "content": {"multipart/form-data": {"schema": {
        "type": "object",
        "required": ["file", "request_id"],
        "properties": {
            "file": {"type": "string", "format": "binary"},
            "request_id": {"type": "string", "format": "uuid"},
            "language": {"type": "string", "enum": ["de", "en"]},
        },
    }}},
}


class TranscriptionOut(BaseModel):
    request_id: UUID
    text: str
    model: str


Slot = Callable[[], AbstractAsyncContextManager[bool]]


def get_transcription_slot() -> Slot:
    return transcription_slot


async def _get_recording(
    request: Request, formats: tuple[str, ...],
) -> tuple[bytes, str, UUID, Literal["de", "en"] | None]:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
        raise audio_error("audio_format_unsupported")
    try:
        async with asyncio.timeout(_UPLOAD_TIMEOUT):
            form = await MultiPartParser(
                request.headers, bounded_body(request, MAX_BYTES + _UPLOAD_OVERHEAD),
                max_files=1, max_fields=2, max_part_size=256,
            ).parse()
    except TimeoutError:
        raise audio_error("audio_timeout") from None
    except (MultiPartException, ClientDisconnect, ValueError):
        raise audio_error("audio_invalid") from None

    try:
        upload = form.get("file")
        request_id = form.get("request_id")
        language = form.get("language")
        if (
            len(form.multi_items()) != len(form) or set(form) - {"file", "request_id", "language"}
            or not isinstance(upload, UploadFile) or not isinstance(request_id, str)
            or language not in {None, "de", "en"}
        ):
            raise audio_error("audio_invalid")
        try:
            parsed_id = UUID(request_id)
        except ValueError:
            raise audio_error("audio_invalid") from None

        declared = (upload.content_type or "").split(";", 1)[0].strip().lower()
        kind = declared.removeprefix("audio/")
        if not declared.startswith("audio/") or kind not in {_FORMATS[value] for value in formats}:
            raise audio_error("audio_format_unsupported")
        if not upload.size:
            raise audio_error("audio_empty")
        if upload.size > MAX_BYTES:
            raise audio_error("audio_too_large")

        report = await run_in_threadpool(check_recording, kind, upload.file)
        if report["status"] != "accepted":
            raise audio_error(_REJECTIONS.get(report["reason"], "audio_unavailable"))
        await upload.seek(0)
        return await upload.read(), kind, parsed_id, language
    finally:
        await form.close()


@router.post(
    "", operation_id="audio_transcribe", summary="Transcribe a recording without submitting a chat turn",
    openapi_extra={"requestBody": _REQUEST_BODY},
    responses={
        401: {"description": "Owner access could not be verified"},
        413: {"description": "Recording too large"},
        415: {"description": "Unsupported recording format"},
        422: {"description": "Invalid or empty recording"},
        429: {"description": "Transcription already in progress or provider rate limit"},
        503: {"description": "Transcription unavailable"},
        504: {"description": "Transcription timed out"},
    },
)
async def transcribe(
    request: Request,
    response: Response,
    provider: Annotated[MistralAudio, Depends(get_audio_provider)],
    slot: Annotated[Slot, Depends(get_transcription_slot)],
) -> TranscriptionOut:
    capability = audio_capabilities().stt
    if capability.status != "available" or capability.model is None:
        raise audio_error("audio_unavailable")
    try:
        async with slot() as acquired:
            if not acquired:
                raise audio_error("audio_rate_limited")
            audio, kind, request_id, language = await _get_recording(request, capability.formats)
            text, model = await provider.transcribe(audio, kind=kind, model=capability.model, language=language)
    except (SQLAlchemyError, OSError):
        raise audio_error("audio_unavailable") from None
    response.headers.update(NO_STORE)
    return TranscriptionOut(request_id=request_id, text=text, model=model)
