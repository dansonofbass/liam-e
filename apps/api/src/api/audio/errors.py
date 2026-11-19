"""Stable refusals for audio requests. Provider and media diagnostics stay private."""

from fastapi import HTTPException

from api.errors import refuse

NO_STORE = {"Cache-Control": "no-store"}

_MESSAGES: dict[str, tuple[int, str]] = {
    "audio_unavailable": (503, "Audio is currently unavailable."),
    "audio_too_large": (413, "The audio request exceeds the size limit."),
    "audio_format_unsupported": (415, "This audio format is not supported."),
    "audio_empty": (422, "The recording contains no usable audio."),
    "audio_too_long": (422, "The recording exceeds the duration limit."),
    "audio_message_unavailable": (404, "The reply is unavailable for speech."),
    "audio_text_too_long": (422, "The reply is too long to read aloud."),
    "audio_invalid": (422, "The audio request is invalid."),
    "audio_rate_limited": (429, "An audio request could not be started yet."),
    "audio_timeout": (504, "The audio request timed out."),
}


def audio_error(code: str) -> HTTPException:
    status, message = _MESSAGES[code]
    error = refuse(status, code, message)
    error.headers = NO_STORE
    return error
