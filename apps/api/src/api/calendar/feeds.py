"""Owner-only feed setup. Never return provider URLs, bodies, titles or diagnostics.

The deployment is single-owner, as in prompts/settings. The scope is server-owned;
clients cannot choose it. Proofs live only in this deployment's database, encrypted
under its key. No proof/address is persisted before the safe parser succeeds.
"""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from db.accessors import calendar_feed_subscription, calendar_feed_validation
from db.engine import get_session_maker
from db.models.calendar_feed_validation import CalendarFeedValidation

from api.calendar import feed_secrets
from api.calendar.ics import ICSAdapter, default_window
from api.calendar.ics_fetch import normalize_url

CONTEXT = "installation"
TTL = timedelta(minutes=10)


class FeedError(ValueError):
    """Fixed diagnostic code only."""


def configuration(*, name: str, url: str, timezone: str, source_id: str | None = None,
                  expected_revision: int | None = None) -> dict:
    try:
        if not 1 <= len(name) <= 80 or not re.fullmatch(r"[\w ()\-]+", name) or not name.strip():
            raise ValueError
        if len(url) > 4096 or len(timezone) > 100:
            raise ValueError
        ZoneInfo(timezone)
        if bool(source_id) != (expected_revision is not None):
            raise ValueError
        return dict(name=name, url=normalize_url(url), timezone=timezone,
                    source_id=source_id, expected_revision=expected_revision)
    except Exception:
        raise FeedError("calendar_feed_invalid") from None


async def purge(now: datetime | None = None) -> None:
    async with get_session_maker()() as session:
        await calendar_feed_validation.purge_expired(session, now=now or datetime.now(UTC))
        await session.commit()


async def discard(token: str) -> None:
    async with get_session_maker()() as session:
        await calendar_feed_validation.discard(session, token_digest=feed_secrets.token_digest(token), context_id=CONTEXT)
        await session.commit()


async def validate(config: dict, *, clock=None) -> dict:
    clock = clock or (lambda: datetime.now(UTC))
    await purge(clock())
    token = feed_secrets.new_token()
    try:
        # Fail before making any request if deployment encryption is unavailable.
        ciphertext = feed_secrets.seal(config)
        start, end = default_window(clock().date())
        snapshot = await ICSAdapter(config["url"], config["timezone"]).snapshot("validation", start, end)
        if not snapshot.complete:
            raise FeedError("calendar_feed_unavailable")
        expires = clock() + TTL
        async with get_session_maker()() as session:
            await calendar_feed_validation.add(session, CalendarFeedValidation(
                token_digest=feed_secrets.token_digest(token), context_id=CONTEXT,
                config_digest=feed_secrets.configuration_digest(token, config),
                encrypted_payload=ciphertext, expires_at=expires))
            await session.commit()
        return dict(validation_id=token, name=config["name"], coverage_start=start, coverage_end=end,
                    occurrence_count=len(snapshot.occurrences), expires_at=expires, format_issues=[])
    except asyncio.CancelledError:
        await asyncio.shield(discard(token))
        raise
    except Exception:
        await discard(token)
        raise FeedError("calendar_feed_unavailable") from None


async def subscribe(token: str, config: dict, *, now: datetime | None = None):
    now = now or datetime.now(UTC)
    await purge(now)
    source = await calendar_feed_subscription.subscribe(
        token_digest=feed_secrets.token_digest(token), context_id=CONTEXT,
        config_digest=feed_secrets.configuration_digest(token, config), now=now,
        name=config["name"], timezone=config["timezone"], source_id=config["source_id"],
        expected_revision=config["expected_revision"])
    if source is None:
        raise FeedError("calendar_validation_expired_or_changed")
    return source
