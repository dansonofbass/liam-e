"""Validate an explicit recording upload and release its temporary file on exit."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Literal
from uuid import UUID

from db.accessors.audio import transcription_slot
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from api.audio.containers import MAX_BYTES, check_recording
from api.audio.errors import audio_error
from api.audio.requests import bounded_body

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
RECORDING_REQUEST_BODY = {
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


Slot = Callable[[], AbstractAsyncContextManager[bool]]


def get_transcription_slot() -> Slot:
    return transcription_slot


@asynccontextmanager
async def validated_recording(
    request: Request, formats: tuple[str, ...],
) -> AsyncIterator[tuple[UploadFile, str, UUID, Literal["de", "en"] | None]]:
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
        yield upload, kind, parsed_id, language
    finally:
        await form.close()
