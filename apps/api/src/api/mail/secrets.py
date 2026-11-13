"""Resolve Mistral workspace secrets by name at runtime — one per IMAP mail account.

The env package's ``WorkspaceSecret`` source fills *settings* at startup; this module resolves
validated account secret names on demand (e.g. ``yahoo-app-password`` for one Yahoo account, another for
iCloud), via ``GET /v1/secrets/values?names=secret:workspace:<name>``. Only the secret's name is
stored in ``mail_credential`` (encrypted) — never its value — so rotating the secret in Mistral
Studio takes effect on the next sync without reconnecting the account.

Secret names in Mistral Studio are lowercase; the lookup lowercases the requested name.
"""

from __future__ import annotations

import importlib
import pkgutil
import re

import env
import httpx
from env import BaseEnv, WorkspaceSecret
from utils.mistral import mistral_api_url, mistral_app_token

_REFERENCE_PREFIX = "secret:workspace:"


class WorkspaceSecretNotFoundError(RuntimeError):
    """Raised when the named workspace secret does not exist (or cannot be read)."""


class SecretNameNotAllowedError(ValueError):
    """The name does not identify a permitted account password secret."""


def app_secret_names() -> frozenset[str]:
    names: set[str] = set()
    for module in pkgutil.iter_modules(env.__path__):
        if module.name.startswith("_"):
            continue
        settings = getattr(importlib.import_module(f"env.{module.name}"), "Env", None)
        if isinstance(settings, type) and issubclass(settings, BaseEnv):
            names.update(
                name.lower() for name, field in settings.model_fields.items()
                if any(isinstance(marker, WorkspaceSecret) for marker in field.metadata)
            )
    return frozenset(names)


def validate_secret_name(name: str) -> str:
    key = name.lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*-app-password", key) or key in app_secret_names():
        raise SecretNameNotAllowedError("Secret name is not allowed")
    return key


async def resolve_workspace_secret(name: str) -> str:
    """The value of the workspace secret ``name`` (lowercase, e.g. ``yahoo-app-password``)."""
    key = validate_secret_name(name)
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
