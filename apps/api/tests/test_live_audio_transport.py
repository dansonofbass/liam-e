"""Browser boundary with synthetic frames and a stub provider."""
from contextlib import asynccontextmanager
import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from conftest import build_app


def test_live_transcription_requires_owner_and_opt_in(monkeypatch):
    from api.audio.access import get_audio_owner_verifier
    from env.audio import env
    from api.routers.api.v1.audio.live import transcription

    class Provider:
        async def append(self, data): assert data == b'\x00\x01'
        async def receive(self):
            await asyncio.sleep(0.01)
            return {'type': 'turn.start', 'time_s': 1.0}

    @asynccontextmanager
    async def fake_live(kind):
        assert kind == 'transcription'
        yield Provider()

    app = build_app()
    async def allow(_): return True
    app.dependency_overrides[get_audio_owner_verifier] = lambda: allow
    monkeypatch.setattr(transcription, 'mistral_live', fake_live)
    monkeypatch.setattr(env, 'audio_studio_owner', json.dumps({'user_id': '00000000-0000-0000-0000-000000000001', 'organization_id': '00000000-0000-0000-0000-000000000002', 'workspace_id': '00000000-0000-0000-0000-000000000003', 'origin': 'https://test.example'}))
    monkeypatch.setattr(env, 'audio_live_test_origin', 'https://test.example')
    monkeypatch.setattr(env, 'audio_live_test_until', (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/v1/audio/live/transcription', headers={'origin': 'https://test.example'}): pass
        monkeypatch.setattr(env, 'audio_live_test_enabled', True)
        monkeypatch.setattr(env, 'audio_live_test_until', (datetime.now(timezone.utc) + timedelta(days=4)).isoformat())
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/v1/audio/live/transcription', headers={'origin': 'https://test.example'}): pass
        monkeypatch.setattr(env, 'audio_live_test_until', (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/v1/audio/live/transcription', headers={'origin': 'https://other.example'}): pass
        with client.websocket_connect('/api/v1/audio/live/transcription', headers={'origin': 'https://test.example'}) as ws:
            ws.send_bytes(b'\x00\x01')
            assert ws.receive_json() == {'type': 'turn.start', 'time_s': 1.0}
            ws.close()
