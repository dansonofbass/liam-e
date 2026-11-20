"""A temporary device check uses the owner boundary and never runs inference."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
import respx
from fastapi.testclient import TestClient

from api.audio.access import get_audio_owner_verifier
from api.audio.provider import get_audio_provider
from api.routers.api.v1.audio.transcriptions import get_transcription_slot
from conftest import build_app
from env.audio import env
from test_audio_transcriptions import REQUEST_ID, recording

PATH = "/api/v1/audio/device-test"


@pytest.fixture
def owner(monkeypatch) -> TestClient:
    async def verified_owner(request):
        return True

    @asynccontextmanager
    async def available():
        yield True

    def forbidden_provider():
        pytest.fail("The device test must not use the live audio provider")

    monkeypatch.setattr(env, "audio_device_test_until",
                        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    monkeypatch.setattr(env, "audio_stt_verification", None)
    monkeypatch.setattr(env, "audio_tts_verification", None)
    app = build_app()
    app.dependency_overrides[get_audio_owner_verifier] = lambda: verified_owner
    app.dependency_overrides[get_transcription_slot] = lambda: available
    app.dependency_overrides[get_audio_provider] = forbidden_provider
    return TestClient(app)


def test_active_device_check_does_not_release_regular_audio(owner) -> None:
    response = owner.get(PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["format"] == "audio/webm;codecs=opus"
    assert response.json()["sample_text"] == "Eine gelbe Ente schwimmt im Teich."
    capabilities = owner.get("/api/v1/audio/capabilities").json()
    assert capabilities["stt"]["status"] == capabilities["tts"]["status"] == "unknown"


@pytest.mark.parametrize("until", [None, "invalid", "2026-01-01T00:00:00Z", "2099-01-01T00:00:00"])
def test_all_device_routes_close_when_disabled_or_expired(owner, monkeypatch, until) -> None:
    monkeypatch.setattr(env, "audio_device_test_until", until)
    for path in (PATH, PATH + "/sample"):
        response = owner.get(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
    assert owner.post(PATH + "/recording", content=b"ignored").status_code == 404


def test_device_check_routes_reject_unverified_callers(client) -> None:
    assert client.get(PATH).status_code == 401
    assert client.get(PATH + "/sample").status_code == 401
    assert client.post(PATH + "/recording", content=b"ignored").status_code == 401


def test_recording_uses_real_validation_but_returns_only_the_fixed_sample(owner, recording) -> None:
    with respx.mock(assert_all_mocked=True) as outbound:
        response = owner.post(
            PATH + "/recording", files={"file": ("sample.webm", recording, "audio/webm")},
            data={"request_id": REQUEST_ID, "language": "de"},
        )
    assert response.status_code == 200
    assert response.json() == {"request_id": REQUEST_ID, "text": "Eine gelbe Ente schwimmt im Teich."}
    assert response.headers["cache-control"] == "no-store"
    assert not outbound.calls


def test_invalid_recording_is_rejected_on_the_device_path(owner) -> None:
    response = owner.post(
        PATH + "/recording", files={"file": ("invalid.webm", b"not media", "audio/webm")},
        data={"request_id": REQUEST_ID},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "audio_format_unsupported"


def test_sample_download_serves_local_mpeg_audio(owner) -> None:
    with respx.mock(assert_all_mocked=True) as outbound:
        response = owner.get(PATH + "/sample")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "audio/mpeg"
    assert 1000 < len(response.content) < 32 * 1024
    assert not outbound.calls
