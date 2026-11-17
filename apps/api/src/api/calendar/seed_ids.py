"""Deterministic development source identities, never connected to a provider."""

from api.mail.seed_ids import seed_id

SEED_CALENDAR_KEYS = ("work", "club", "old", "uncovered", "paused")
SEED_CALENDAR_IDS = frozenset(seed_id("calendar", key) for key in SEED_CALENDAR_KEYS)
