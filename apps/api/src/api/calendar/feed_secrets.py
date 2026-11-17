"""Private feed payloads use the existing deployment Fernet key.

Proof tokens are random capabilities. Only their digest is stored. Configuration
fingerprints are keyed by the token so a database dump does not enable guessing
private addresses from an unkeyed URL hash. Never log arguments or return payloads
from management endpoints.
"""

import hashlib
import hmac
import json
import secrets
from typing import Any

from api.mail.crypto import decrypt_payload, encrypt_payload


class FeedSecretError(ValueError):
    """Fixed public code, without chained cryptographic or input diagnostics."""


def seal(payload: dict[str, Any]) -> str:
    try:
        return encrypt_payload(payload)
    except Exception:
        raise FeedSecretError("calendar_secret_unavailable") from None


def unseal(ciphertext: str) -> dict[str, Any]:
    try:
        return decrypt_payload(ciphertext)
    except Exception:
        raise FeedSecretError("calendar_secret_unavailable") from None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def configuration_digest(token: str, configuration: dict[str, Any]) -> str:
    canonical = json.dumps(configuration, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hmac.new(token.encode(), canonical.encode(), hashlib.sha256).hexdigest()
