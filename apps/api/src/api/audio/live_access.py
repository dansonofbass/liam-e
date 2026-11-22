"""Separate opt-in bound to the same explicitly configured test owner origin."""
from datetime import datetime, timedelta, timezone

from env.audio import env
from pydantic import ValidationError
from starlette.requests import HTTPConnection

from api.audio.access import _StudioOwner


def live_remaining(connection: HTTPConnection) -> float:
    if not env.audio_live_test_enabled or not env.audio_live_test_origin or not env.audio_studio_owner:
        return 0
    try:
        expiry = datetime.fromisoformat(env.audio_live_test_until or '')
        now = datetime.now(timezone.utc)
        if expiry.utcoffset() is None or not now < expiry <= now + timedelta(days=3):
            return 0
        owner = _StudioOwner.model_validate_json(env.audio_studio_owner)
    except (ValidationError, ValueError):
        return 0
    if connection.headers.get('origin') != env.audio_live_test_origin or owner.origin != env.audio_live_test_origin:
        return 0
    return (expiry - now).total_seconds()


def live_allowed(connection: HTTPConnection) -> bool:
    return live_remaining(connection) > 0
