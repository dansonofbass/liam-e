"""Feed addresses stay inside deployment-encrypted payloads."""

import pytest
from cryptography.fernet import Fernet

from api.calendar import feed_secrets
from env.mail import env


def test_private_payload_and_proof_fingerprints(monkeypatch):
    monkeypatch.setattr(env, "mail_token_encryption_key", Fernet.generate_key().decode())
    payload = {"url": "https://calendar.example/test-only?token=test-only", "timezone": "UTC"}
    ciphertext = feed_secrets.seal(payload)
    assert "calendar.example" not in ciphertext and "test-only" not in ciphertext
    assert feed_secrets.unseal(ciphertext) == payload
    first, second = feed_secrets.new_token(), feed_secrets.new_token()
    assert first != second and len(first) >= 43
    assert feed_secrets.token_digest(first) != first
    digest = feed_secrets.configuration_digest(first, payload)
    assert digest != feed_secrets.configuration_digest(second, payload)
    assert digest != feed_secrets.configuration_digest(first, {**payload, "timezone": "Europe/Berlin"})
    assert digest != feed_secrets.configuration_digest(first, {**payload, "url": payload["url"] + "-changed"})
    monkeypatch.setattr(env, "mail_token_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(feed_secrets.FeedSecretError, match="^calendar_secret_unavailable$") as caught:
        feed_secrets.unseal(ciphertext)
    assert caught.value.__suppress_context__


def test_encryption_failures_have_fixed_diagnostics(monkeypatch):
    def fail(*args):
        raise ValueError("https://calendar.example/test-only")
    monkeypatch.setattr(feed_secrets, "encrypt_payload", fail)
    with pytest.raises(feed_secrets.FeedSecretError) as caught:
        feed_secrets.seal({"url": "https://calendar.example/test-only"})
    assert str(caught.value) == "calendar_secret_unavailable"
    assert caught.value.__suppress_context__
