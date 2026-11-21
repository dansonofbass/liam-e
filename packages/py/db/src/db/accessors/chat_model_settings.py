"""Revision-checked default chat model shared across devices."""
from sqlalchemy.dialects.postgresql import insert

from db.accessors.prompt_template import StaleVersion
from db.engine import get_session_maker
from db.models.chat_model_settings import ChatModelSettings
from db.models.prompt_template import OWNER_SCOPE


async def in_session(session) -> ChatModelSettings:
    return await session.get(ChatModelSettings, OWNER_SCOPE) or ChatModelSettings()


async def get() -> ChatModelSettings:
    async with get_session_maker()() as session:
        return await in_session(session)


async def update(expected_version: int, default_model: str | None) -> ChatModelSettings:
    async with get_session_maker().begin() as session:
        await session.execute(
            insert(ChatModelSettings).values(**ChatModelSettings().model_dump()).on_conflict_do_nothing()
        )
        row = await session.get(ChatModelSettings, OWNER_SCOPE, with_for_update=True)
        if row.version != expected_version:
            raise StaleVersion
        if row.default_model != default_model:
            row.default_model = default_model
            row.version += 1
        return row
