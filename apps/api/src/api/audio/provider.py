"""Stateless Mistral audio inference with fixed provider paths and bounded responses."""

import asyncio
import json
import re
from typing import Any

import httpx

from api.audio.capabilities import MODEL_PATTERN
from api.audio.errors import audio_error
from utils.mistral import MistralNotConfiguredError, mistral_app_token

_TRANSCRIPTION_TIMEOUT = 20
_MAX_TRANSCRIPTION_RESPONSE = 256 * 1024


async def _audio_request(path: str, *, timeout: int, max_response_bytes: int, **payload: Any) -> dict:
    try:
        async with asyncio.timeout(timeout):
            token = mistral_app_token()
            async with httpx.AsyncClient(
                base_url="https://api.mistral.ai", timeout=timeout, trust_env=False, follow_redirects=False,
            ) as client, client.stream(
                "POST", path, headers={"Authorization": f"Bearer {token}"}, **payload,
            ) as response:
                if response.status_code == 429:
                    raise audio_error("audio_rate_limited")
                if response.status_code in {408, 504}:
                    raise audio_error("audio_timeout")
                if response.status_code != 200:
                    raise audio_error("audio_unavailable")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > max_response_bytes:
                        raise audio_error("audio_unavailable")
                    body.extend(chunk)
    except (TimeoutError, httpx.TimeoutException):
        raise audio_error("audio_timeout") from None
    except (MistralNotConfiguredError, httpx.HTTPError, ValueError):
        raise audio_error("audio_unavailable") from None

    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):
        raise audio_error("audio_unavailable") from None
    if not isinstance(parsed, dict):
        raise audio_error("audio_unavailable")
    return parsed


class MistralAudio:
    async def transcribe(
        self, data: bytes, *, kind: str, model: str, language: str | None,
    ) -> tuple[str, str]:
        form = {"model": model}
        if language is not None:
            form["language"] = language
        result = await _audio_request(
            "/v1/audio/transcriptions", timeout=_TRANSCRIPTION_TIMEOUT,
            max_response_bytes=_MAX_TRANSCRIPTION_RESPONSE, data=form,
            files={"file": (f"recording.{kind}", data, f"audio/{kind}")},
        )
        text, reported_model = result.get("text"), result.get("model")
        if not isinstance(text, str) or not isinstance(reported_model, str) or not re.fullmatch(MODEL_PATTERN, reported_model):
            raise audio_error("audio_unavailable")
        if not text.strip():
            raise audio_error("audio_empty")
        return text.strip(), reported_model


def get_audio_provider() -> MistralAudio:
    return MistralAudio()
