"""Revision-checked default calendar shared across devices."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.accessors import calendar_source
from db.accessors.prompt_template import StaleVersion
from db.engine import get_session_maker
from db.models.calendar_settings import CalendarSettings
from db.models.calendar_source import CalendarSource
from db.models.calendar_sync_state import CalendarSyncState
from db.models.prompt_template import OWNER_SCOPE


class CalendarNotWritable(ValueError):
    pass


async def get() -> CalendarSettings:
    async with get_session_maker()() as session:
        return await session.get(CalendarSettings, OWNER_SCOPE) or CalendarSettings()


async def update(expected_version: int, source_id: str | None) -> CalendarSettings:
    async with get_session_maker().begin() as session:
        await session.execute(insert(CalendarSettings).values(**CalendarSettings().model_dump()).on_conflict_do_nothing())
        row = await session.get(CalendarSettings, OWNER_SCOPE, with_for_update=True)
        if row.version != expected_version:
            raise StaleVersion
        if source_id is not None:
            source = await session.scalar(select(CalendarSource).where(CalendarSource.id == source_id).with_for_update())
            state = await session.get(CalendarSyncState, source_id)
            if not source or calendar_source.chat_access(source, state) != "writable":
                raise CalendarNotWritable
        if row.default_source_id != source_id:
            row.default_source_id = source_id
            row.version += 1
        return row
