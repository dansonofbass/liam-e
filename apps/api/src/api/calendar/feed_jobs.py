"""ICS adapter and persistent, bounded polling of ICS and Google calendars."""

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from db.accessors import calendar_feed_sync, calendar_source
from env.calendar import env

from api.calendar import feed_secrets, feeds
from api.calendar.adapters import Event, Snapshot
from api.calendar.ics import ICSAdapter, ICSError
from api.calendar.seed_ids import SEED_CALENDAR_IDS


@dataclass(frozen=True)
class FeedSnapshot(Snapshot):
    encrypted_validators: str = field(repr=False)
    source_revision: int


class StoredICSAdapter:
    def __init__(self, *, clock=None, jitter=None):
        self.clock = clock or (lambda: datetime.now(UTC))
        self.jitter = jitter or random.uniform

    async def snapshot(self, source_id, start, end):
        source, config, state, stored = await calendar_feed_sync.inputs(source_id)
        try:
            if config is None:
                raise ICSError("configuration_missing")
            private = feed_secrets.unseal(config.encrypted_payload)
            validators = feed_secrets.unseal(state.encrypted_validators) if state and state.encrypted_validators else {}
            previous = [Event(e.external_id, e.title, json.loads(e.recurrence_json)) for e in stored] if validators else None
            adapter = ICSAdapter(private["url"], source.timezone, previous_events=previous,
                                 etag=validators.get("etag"), last_modified=validators.get("last_modified"))
            snapshot = await adapter.snapshot(source_id, start, end)
            result = adapter.last_result
            if not snapshot.complete or result is None:
                raise ICSError("incomplete")
            current = {"etag": result.etag, "last_modified": result.last_modified}
            if result.code == "not_modified":
                current = {key: value or validators.get(key) for key, value in current.items()}
            return FeedSnapshot(snapshot.events, snapshot.occurrences, True, feed_secrets.seal(current), source.revision)
        except Exception as error:
            code = str(error) if isinstance(error, ICSError) else "feed_error"
            retry = code in {"rate_limited", "provider_error", "timeout", "fetch_error"}
            public_code = "address_check" if code in {"auth_required", "not_found"} else "feed_unavailable"
            failures = state.failure_count if state else 0
            await calendar_feed_sync.failure(source_id, revision=source.revision, now=self.clock(),
                                             code=public_code, delay_seconds=self.jitter(30, 60) * 2 ** min(failures, 2) if retry else None)
            # The calendar scheduler owns retry timing, not the mail worker's generic retries.
            raise LookupError("calendar_feed_unavailable") from None


async def enqueue(source_id: str, *, manual: bool, now: datetime | None = None) -> bool:
    if source_id in SEED_CALENDAR_IDS:
        return False
    source = await calendar_source.get(source_id)
    interval = (env.calendar_google_sync_interval_minutes if source and source.provider == "google"
                else env.calendar_sync_interval_minutes)
    return await calendar_feed_sync.enqueue(source_id, now=now or datetime.now(UTC),
                                            interval=interval, manual=manual)


async def enqueue_due(now: datetime) -> None:
    await feeds.purge(now)
    for source in await calendar_source.list_active():
        if source.provider in {"ics", "google"}:
            await enqueue(source.id, manual=False, now=now)
