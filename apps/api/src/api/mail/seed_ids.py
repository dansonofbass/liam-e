"""Stable identifiers for local sample accounts, without database dependencies."""

from uuid import UUID, uuid5

SEED_NAMESPACE = UUID("e7a6334c-ec02-4ac7-b7b0-14e98b91e689")


def seed_id(kind: str, key: str) -> str:
    return str(uuid5(SEED_NAMESPACE, f"{kind}:{key}"))


SEED_ACCOUNT_IDS = frozenset(seed_id("account", key) for key in ("privat", "arbeit", "verein", "familie"))


def is_seed_account(account_id: str) -> bool:
    return account_id in SEED_ACCOUNT_IDS
