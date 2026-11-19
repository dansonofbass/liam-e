"""Read a bounded request after the audio owner dependency has run."""

from collections.abc import AsyncIterator

from fastapi import Request

from api.audio.errors import audio_error


async def bounded_body(request: Request, limit: int) -> AsyncIterator[bytes]:
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise audio_error("audio_too_large")
        yield chunk
