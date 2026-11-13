"""At-rest encryption for mail credentials (OAuth tokens, IMAP app passwords).

Payloads are JSON-serialized and encrypted with Fernet (AES-128-CBC + HMAC) under
``MAIL_TOKEN_ENCRYPTION_KEY``. The key lives only in the environment / Mistral workspace secrets,
never in the database, the code, or logs.
"""

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from env.mail import env as mail_env


class TokenEncryptionNotConfiguredError(RuntimeError):
    """Raised when a credential must be encrypted but no key is configured (or it does not match)."""


def new_key() -> str:
    """A fresh Fernet key, for generating ``MAIL_TOKEN_ENCRYPTION_KEY`` (store it as a workspace secret)."""
    return Fernet.generate_key().decode()


def _fernet() -> Fernet:
    key = mail_env.mail_token_encryption_key
    if not key:
        raise TokenEncryptionNotConfiguredError(
            "MAIL_TOKEN_ENCRYPTION_KEY is not set. Generate one with "
            '`bash tools/uv.sh run --no-sync python -c "from api.mail.crypto import new_key; print(new_key())"` '
            "and store it as a workspace secret (or in the local .env)."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_payload(payload: dict[str, Any]) -> str:
    """Encrypt a JSON-serializable credential payload for storage in ``mail_credential``."""
    return _fernet().encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()


def decrypt_payload(token: str) -> dict[str, Any]:
    """Decrypt a payload produced by :func:`encrypt_payload`. Raises when the key does not match."""
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except InvalidToken as error:
        raise TokenEncryptionNotConfiguredError(
            "A stored mail credential cannot be decrypted: MAIL_TOKEN_ENCRYPTION_KEY does not match the key it was encrypted with."
        ) from error
