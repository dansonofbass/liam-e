"""Server-side owner verification boundary for browser audio."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request

AudioOwnerVerifier = Callable[[Request], Awaitable[bool]]


async def _deny_unverified_owner(request: Request) -> bool:
    return False


def get_audio_owner_verifier() -> AudioOwnerVerifier:
    """Install a verified owner check server-side before exposing the audio subtree."""
    return _deny_unverified_owner


async def require_audio_owner(
    request: Request,
    verify: Annotated[AudioOwnerVerifier, Depends(get_audio_owner_verifier)],
) -> None:
    if await verify(request) is not True:
        raise HTTPException(status_code=401, detail="unauthorized", headers={"Cache-Control": "no-store"})
