"""The browser upload is owner-only and requires its own release evidence."""

import json
import shutil
import subprocess
from contextlib import asynccontextmanager

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from conftest import build_app

PATH = "/api/v1/audio/transcriptions"


def test_transcription_rejects_unverified_owner_before_parsing_upload(client: TestClient) -> None:
    response = client.post(PATH, content=b"synthetic invalid body")

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_transcription_is_closed_without_release_evidence(monkeypatch) -> None:
    from api.audio.access import get_audio_owner_verifier
    from env.audio import env

    async def verified_owner(request):
        return True

    monkeypatch.setattr(env, "audio_stt_verification", None)
    app = build_app()
    app.dependency_overrides[get_audio_owner_verifier] = lambda: verified_owner

    response = TestClient(app).post(PATH, content=b"synthetic invalid body")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "audio_unavailable"
    assert response.headers["cache-control"] == "no-store"


REQUEST_ID = "01574e25-1d4a-4af4-adad-662f9bb47317"


@pytest.fixture
def released_stt(monkeypatch) -> TestClient:
    from api.audio.access import get_audio_owner_verifier
    from api.routers.api.v1.audio.transcriptions import get_transcription_slot
    from env.audio import env
    from env.mistral import env as mistral

    async def owner(request):
        return True

    @asynccontextmanager
    async def slot():
        yield True

    monkeypatch.setattr(env, "audio_stt_model", "voxtral-mini-transcribe-3")
    monkeypatch.setattr(env, "audio_stt_verification", json.dumps({
        "model": env.audio_stt_model, "checked_at": "2026-01-01T10:00:00Z",
        "outcome": "verified", "scope": "studio_release", "formats": ["audio/webm;codecs=opus"],
        "app_limits": {"max_upload_bytes": 10_485_760, "max_duration_seconds": 120, "max_concurrent_requests": 1},
    }))
    monkeypatch.setattr(mistral, "mistral_api_key", "test-only")
    app = build_app()
    app.dependency_overrides[get_audio_owner_verifier] = lambda: owner
    app.dependency_overrides[get_transcription_slot] = lambda: slot
    return TestClient(app)


@pytest.fixture
def recording() -> bytes:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are needed for synthetic recordings")
    for tool in ("ffmpeg", "ffprobe"):
        protocols = subprocess.check_output([tool, "-protocols"], stderr=subprocess.DEVNULL, timeout=5)
        if b"fd" not in protocols.split():
            pytest.skip("The validator requires the FFmpeg descriptor protocol")
    return subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.25",
        "-c:a", "libopus", "-f", "webm", "pipe:1",
    ], capture_output=True, check=True, timeout=5).stdout


def post_recording(client, audio, mime="audio/webm"):
    return client.post(PATH, files={"file": ("synthetic.webm", audio, mime)},
                       data={"request_id": REQUEST_ID, "language": "de"})


def test_transcription_uses_real_media_validation_and_returns_editable_text(released_stt, recording):
    with respx.mock(assert_all_mocked=True) as outbound:
        provider = outbound.post("https://api.mistral.ai/v1/audio/transcriptions").mock(
            return_value=Response(200, json={"model": "voxtral-mini-transcribe-3", "text": "Synthetischer Satz."}),
        )
        response = post_recording(released_stt, recording)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"request_id": REQUEST_ID, "model": "voxtral-mini-transcribe-3", "text": "Synthetischer Satz."}
    assert provider.call_count == 1
    assert recording in provider.calls[0].request.content


@pytest.mark.parametrize(("audio", "mime", "status", "code"), [
    (b"", "audio/webm", 422, "audio_empty"),
    (b"synthetic wrong container", "audio/webm", 415, "audio_format_unsupported"),
    (b"synthetic", "audio/mp4", 415, "audio_format_unsupported"),
    (bytes(10_485_761), "audio/webm", 413, "audio_too_large"),
])
def test_rejected_uploads_never_call_provider(released_stt, audio, mime, status, code):
    with respx.mock(assert_all_mocked=True) as outbound:
        response = post_recording(released_stt, audio, mime)

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert not outbound.calls


def test_rate_limit_rejects_before_reading_upload(released_stt):
    from api.routers.api.v1.audio.transcriptions import get_transcription_slot

    @asynccontextmanager
    async def busy():
        yield False

    released_stt.app.dependency_overrides[get_transcription_slot] = lambda: busy
    response = released_stt.post(PATH, content=b"synthetic non-multipart body")
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "audio_rate_limited"
