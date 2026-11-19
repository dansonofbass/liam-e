"""Server-side owner verification boundary for browser audio."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Annotated
from uuid import UUID

from env.audio import env
from fastapi import Depends, HTTPException, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from utils.mistral import MistralNotConfiguredError, caller_credentials

AudioOwnerVerifier = Callable[[Request], Awaitable[bool]]
_LOG = logging.getLogger(__name__)
_MAX_IDENTITY_BYTES = 16 * 1024


class _StudioOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    organization_id: UUID
    workspace_id: UUID
    origin: str = Field(pattern=r"^https://[a-zA-Z0-9.-]+(?::[0-9]+)?$")


class _StudioScope(BaseModel):
    id: UUID


class _StudioUser(BaseModel):
    id: UUID
    organization: _StudioScope
    workspace: _StudioScope
    api_key: None


async def _verify_studio_owner(request: Request) -> bool:
    configured = env.audio_studio_owner
    if not configured or len(configured) > 1024 or "x-api-key" in request.headers:
        return False
    try:
        owner = _StudioOwner.model_validate_json(configured)
        if request.method not in {"GET", "HEAD"} and request.headers.get("origin") != owner.origin:
            return False
        credentials = caller_credentials()
    except (MistralNotConfiguredError, ValidationError):
        return False
    if not credentials:
        return False

    # The gateway proxy is installed by the runtime. The user lookup must use the current
    # request's bearer alone. The app key identifies a deployment, even if its creator is the owner.
    try:
        async with asyncio.timeout(4), httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                "GET", f"{credentials.server_url.rstrip('/')}/v1/users/me",
                headers={"Authorization": f"Bearer {credentials.token}", "Accept": "application/json"},
            ) as response:
                if response.status_code != 200:
                    _LOG.info("Studio audio identity lookup returned HTTP %d", response.status_code)
                    return False
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_IDENTITY_BYTES:
                        return False
                    body.extend(chunk)
        identity = _StudioUser.model_validate_json(body)
    except (TimeoutError, httpx.HTTPError, httpx.InvalidURL, ValidationError):
        _LOG.info("Studio audio identity lookup did not establish a scoped browser session")
        return False
    return (
        identity.id == owner.user_id
        and identity.organization.id == owner.organization_id
        and identity.workspace.id == owner.workspace_id
    )


def get_audio_owner_verifier() -> AudioOwnerVerifier:
    return _verify_studio_owner


async def require_audio_owner(
    request: Request,
    verify: Annotated[AudioOwnerVerifier, Depends(get_audio_owner_verifier)],
) -> None:
    if await verify(request) is not True:
        raise HTTPException(status_code=401, detail="unauthorized", headers={"Cache-Control": "no-store"})
