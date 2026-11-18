"""Calendar source storage."""

import json
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from db.engine import get_session_maker
from db.accessors._calendar_lock import lock_source
from db.models.calendar_source import CalendarSource
from db.models.calendar_event import CalendarEvent
from db.models.calendar_feed_config import CalendarFeedConfig
from db.models.calendar_occurrence import CalendarOccurrence
from db.models.calendar_sync_state import CalendarSyncState
from db.models.mail_job import MailJob


async def get(source_id: str) -> CalendarSource | None:
    async with get_session_maker()() as session:
        return await session.get(CalendarSource, source_id)


async def list_all() -> list[CalendarSource]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(CalendarSource).order_by(CalendarSource.id))).scalars())


async def set_active(source_id: str, active: bool) -> CalendarSource | None:
    async with get_session_maker()() as session:
        row = (await session.execute(select(CalendarSource).where(CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if row is not None:
            if row.is_active != active:
                row.revision += 1
            row.is_active = active
            await session.commit()
        return row


async def remove(source_id: str) -> bool:
    async with get_session_maker()() as session:
        await lock_source(session, source_id)
        # Match snapshot lock ordering so deletion cannot deadlock with activation.
        await session.execute(delete(MailJob).where(MailJob.dedupe_key == f"calendar_sync:{source_id}"))
        row = (await session.execute(select(CalendarSource).where(CalendarSource.id == source_id).with_for_update())).scalar_one_or_none()
        if row is None:
            return False
        for model in (CalendarOccurrence, CalendarEvent, CalendarSyncState, CalendarFeedConfig):
            await session.execute(delete(model).where(model.source_id == source_id))
        await session.delete(row)
        await session.commit()
        return True


async def list_connection(provider: str, connection_ref: str) -> list[CalendarSource]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(CalendarSource).where(
            CalendarSource.provider == provider, CalendarSource.connection_ref == connection_ref))).scalars())


async def connect_google(connection_ref: str, calendars: list[dict], *, now: datetime,
                         interval: int) -> list[CalendarSource]:
    """Create missing selections and first manual jobs atomically; never re-home sources."""
    result = {}
    async with get_session_maker()() as session:
        # Stable lock order also makes concurrent requests with reversed selections safe.
        for calendar in sorted(calendars, key=lambda item: item["id"]):
            row = CalendarSource(provider="google", connection_ref=connection_ref,
                                 external_id=calendar["id"], name=calendar["name"].strip()[:80],
                                 timezone=calendar["timezone"], capabilities_json='["read"]')
            created = (await session.execute(insert(CalendarSource).values(**row.model_dump())
                .on_conflict_do_nothing(constraint="uq_calendar_source_external")
                .returning(CalendarSource.id))).scalar_one_or_none()
            if created is not None:
                job = MailJob(kind="calendar_sync", payload_json=json.dumps({"source_id": created}),
                              dedupe_key=f"calendar_sync:{created}", run_after=now)
                session.add(job)
                session.add(CalendarSyncState(source_id=created, last_checked_at=now,
                                               next_attempt_at=now + timedelta(minutes=interval)))
            stored = (await session.execute(select(CalendarSource).where(
                CalendarSource.provider == "google", CalendarSource.connection_ref == connection_ref,
                CalendarSource.external_id == calendar["id"]).with_for_update())).scalar_one()
            result[stored.external_id] = stored
        await session.commit()
    return [result[calendar["id"]] for calendar in calendars]


async def list_active() -> list[CalendarSource]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(CalendarSource).where(CalendarSource.is_active.is_(True)).order_by(CalendarSource.id))).scalars())
