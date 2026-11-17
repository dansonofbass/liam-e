"""Fail-closed integration boundary for a future independently verified read grant.

The default verifier deliberately rejects every request. A future transport must install a
verified implementation and pass its grant to the same services as the HTTP facade.
"""

from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, HTTPException, Request


@dataclass(frozen=True)
class ReadGrant:
    account_ids: frozenset[str]


class ReadAccessVerifier(Protocol):
    async def verify(self, request: Request) -> ReadGrant: ...


class DenyReadAccess:
    async def verify(self, request: Request) -> ReadGrant:
        raise HTTPException(status_code=401, detail="unauthorized")


def get_read_access_verifier() -> ReadAccessVerifier:
    return DenyReadAccess()


async def require_read_access(
    request: Request, verifier: ReadAccessVerifier = Depends(get_read_access_verifier)
) -> ReadGrant:
    return await verifier.verify(request)


def restrict_accounts(grant: ReadGrant, requested: list[str] | None) -> frozenset[str]:
    """Resolve an optional selection without ever widening the verified grant."""
    if requested is None:
        return grant.account_ids
    selected = frozenset(requested)
    if not selected <= grant.account_ids:
        raise HTTPException(status_code=403, detail="insufficient_scope")
    return selected
