"""Serve the real API with local identity and provider fixtures for the audio browser test."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

# The browser runner provisions a fresh local database with this exact name.
database = urlsplit(os.environ["DATABASE_URL"])
if database.hostname != "127.0.0.1" or database.path != "/liam_e_audio_e2e" or database.query:
    raise SystemExit("Audio e2e needs its disposable loopback database")

os.environ.update(TELEMETRY_ENABLED="false", MISTRAL_SECRETS_ENABLED="false", MAIL_WORKER_ENABLED="false")

import uvicorn
from db.accessors import chat_message
from db.accessors.audio import transcription_slot
from mistralai_capabilities.fastapi.hooks import FastAPIHooks

from api.audio.access import get_audio_owner_verifier
from api.audio.provider import get_audio_provider
from api.mail.chat_events import DeltaEvent, DoneEvent, StartEvent
from api.mail.chat_schemas import ChatExtrasOut
from api.mail.dev_seed import seed, seed_id
from api.mail.models_catalog import ChatModelOut
from api.main import create_app
from api.routers.api.v1.chat import models, stream
from env.audio import env as audio

CONVERSATION = seed_id("conversation", "was-ist-heute-wichtig")
CHAT_MODEL = "mistral-medium-latest"
TRANSCRIPT = "Ein synthetischer Satz."
ANSWER = "Hier ist die **synthetische Antwort**."


class AudioFixture:
    async def transcribe(self, data, *, kind, model, language):
        assert kind == "webm" and data and language == "de"
        return TRANSCRIPT, model

    async def synthesize(self, text, *, model, limits):
        assert text == "Hier ist die synthetische Antwort."
        assert model == "voxtral-mini-tts-3-0"
        result = await asyncio.to_thread(subprocess.run, [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.8",
            "-f", "mp3", "pipe:1",
        ], capture_output=True, check=True, timeout=5)
        assert 0 < len(result.stdout) <= limits.max_response_bytes
        return result.stdout


async def loopback_owner(request):
    return request.client is not None and request.client.host == "127.0.0.1"


async def fixture_models():
    return [ChatModelOut(id=CHAT_MODEL, label="Mistral Medium", description="", is_default=True)]


async def fixture_chat_turn(*, conversation_id, text, **unused):
    user = await chat_message.add_message(conversation_id=conversation_id, role="user", content=text)
    yield StartEvent(conversation_id=conversation_id, user_message_id=user.id, model=CHAT_MODEL)
    yield DeltaEvent(text=ANSWER)
    reply = await chat_message.add_message(conversation_id=conversation_id, role="assistant", content=ANSWER,
                                          extras_json=ChatExtrasOut(model=CHAT_MODEL).model_dump_json())
    yield DoneEvent(conversation_id=conversation_id, message_id=reply.id, stopped=False)


async def serve(port: int) -> None:
    await seed()
    # Use the actual Postgres guard. A second connection must be refused until release.
    async with transcription_slot() as first:
        async with transcription_slot() as competing:
            assert first and not competing
    async with transcription_slot() as again:
        assert again

    audio.audio_stt_model = "voxtral-mini-transcribe-3"
    audio.audio_device_test_until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    audio.audio_stt_verification = json.dumps({
        "model": audio.audio_stt_model, "checked_at": "2026-01-01T10:00:00Z",
        "outcome": "verified", "scope": "studio_release", "formats": ["audio/webm;codecs=opus"],
        "app_limits": {"max_upload_bytes": 10_485_760, "max_duration_seconds": 120, "max_concurrent_requests": 1},
    })
    audio.audio_tts_model = "voxtral-mini-tts-3-0"
    audio.audio_tts_verification = json.dumps({
        "model": audio.audio_tts_model, "checked_at": "2026-01-01T10:00:00Z",
        "outcome": "verified", "scope": "studio_release", "formats": ["audio/mpeg"],
        "app_limits": {"max_input_characters": 500, "max_response_bytes": 1_000_000, "timeout_seconds": 20},
    })
    models.list_chat_models = fixture_models
    stream.run_turn_events = fixture_chat_turn
    app = create_app(hooks=FastAPIHooks.empty())
    app.dependency_overrides[get_audio_owner_verifier] = lambda: loopback_owner
    app.dependency_overrides[get_audio_provider] = AudioFixture
    config = uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, proxy_headers=False)
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(serve(int(sys.argv[1])))
