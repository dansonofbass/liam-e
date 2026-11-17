"""Fail-closed integration boundary for a future independently verified read grant.

The default verifier deliberately rejects every request. A future transport must install a
verified implementation and pass its grant to the same services as the HTTP facade.
"""

from dataclasses import dataclass
import re
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
    return validate_grant(await verifier.verify(request))


def validate_grant(grant: ReadGrant) -> ReadGrant:
    """Reject malformed or oversized grants rather than returning an unbounded envelope."""
    if (not isinstance(grant, ReadGrant) or not isinstance(grant.account_ids, frozenset)
            or len(grant.account_ids) > 100
            or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value)
                   for value in grant.account_ids)):
        raise HTTPException(status_code=401, detail="unauthorized")
    return grant


def restrict_accounts(grant: ReadGrant, requested: list[str] | None) -> frozenset[str]:
    """Resolve an optional selection without ever widening the verified grant."""
    validate_grant(grant)
    if requested is None:
        return grant.account_ids
    selected = frozenset(requested)
    if not selected <= grant.account_ids:
        raise HTTPException(status_code=403, detail="insufficient_scope")
    return selected
