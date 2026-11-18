"""Atomic proof consumption, private configuration replacement and initial job."""

import json
from datetime import datetime

from sqlalchemy import delete, select

from db.accessors.calendar_feed_validation import consume
from db.accessors._calendar_lock import lock_source
from db.engine import get_session_maker
from db.models.calendar_feed_config import CalendarFeedConfig
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState
from db.models.mail_job import MailJob


async def subscribe(*, token_digest: str, context_id: str, config_digest: str, now: datetime,
                    name: str, timezone: str, source_id: str | None, expected_revision: int | None) -> CalendarSource | None:
    async with get_session_maker()() as session:
        # Job -> source is the same lock order as snapshot activation/removal.
        if source_id:
            await lock_source(session, source_id)
            await session.execute(delete(MailJob).where(MailJob.dedupe_key == f"calendar_sync:{source_id}"))
            source = (await session.execute(select(CalendarSource).where(
                CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
            if source is None or source.provider != "ics" or source.revision != expected_revision:
                return None
        else:
            source = CalendarSource(provider="ics", connection_ref="private", external_id=token_digest,
                                    name=name, timezone=timezone, capabilities_json='["read"]')
        proof = await consume(session, token_digest=token_digest, context_id=context_id,
                              config_digest=config_digest, now=now)
        if proof is None:
            return None
        if source_id:
            source.revision += 1
            source.name, source.timezone = name, timezone
            # Retain the last valid generation, but never send old validators to a new address.
            state = await session.get(CalendarSyncState, source.id)
            if state:
                state.encrypted_validators = None
                state.last_checked_at = state.next_attempt_at = None
                state.last_error = None
                state.failure_count = 0
                state.incomplete = True
        session.add(source)
        config = await session.get(CalendarFeedConfig, source.id)
        if config:
            config.encrypted_payload = proof.encrypted_payload
        else:
            session.add(CalendarFeedConfig(source_id=source.id, encrypted_payload=proof.encrypted_payload))
        if source.is_active:
            session.add(MailJob(kind="calendar_sync", payload_json=json.dumps({"source_id": source.id}),
                                dedupe_key=f"calendar_sync:{source.id}", run_after=now))
        await session.commit()
        return source
