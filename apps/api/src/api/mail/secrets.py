"""Resolve Mistral workspace secrets by name at runtime — one per IMAP mail account.

The env package's ``WorkspaceSecret`` source fills *settings* at startup; this module resolves
*arbitrary* secret names on demand (e.g. ``yahoo-app-password`` for one Yahoo account, another for
iCloud), via ``GET /v1/secrets/values?names=secret:workspace:<name>``. Only the secret's name is
stored in ``mail_credential`` (encrypted) — never its value — so rotating the secret in Mistral
Studio takes effect on the next sync without reconnecting the account.

Secret names in Mistral Studio are lowercase; the lookup lowercases the requested name.
"""

from __future__ import annotations

import httpx
from utils.mistral import mistral_api_url, mistral_app_token

_REFERENCE_PREFIX = "secret:workspace:"


class WorkspaceSecretNotFoundError(RuntimeError):
    """Raised when the named workspace secret does not exist (or cannot be read)."""


async def resolve_workspace_secret(name: str) -> str:
    """The value of the workspace secret ``name`` (lowercase, e.g. ``yahoo-app-password``)."""
    key = name.strip().lower().removeprefix(_REFERENCE_PREFIX)
    if not key:
        raise ValueError("empty secret name")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{mistral_api_url()}/v1/secrets/values",
            headers={"Authorization": f"Bearer {mistral_app_token()}"},
            params={"names": _REFERENCE_PREFIX + key},
        )
    if response.status_code == 404:
        raise WorkspaceSecretNotFoundError(
            f"Workspace-Secret {key!r} nicht gefunden — in Mistral Studio anlegen (lowercase)."
        )
    response.raise_for_status()
    for item in response.json():
        if str(item.get("name", "")).lower() == _REFERENCE_PREFIX + key:
            return str(item["value"])
    raise WorkspaceSecretNotFoundError(f"Workspace-Secret {key!r} nicht gefunden.")
