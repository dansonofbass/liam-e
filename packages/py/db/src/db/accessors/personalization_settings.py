"""Sectioned personalization settings, serialized with preference resolution/mutations."""
from db.engine import get_session_maker
from db.models.personalization_settings import PersonalizationSettings
from db.models.prompt_template import OWNER_SCOPE
from db.accessors.prompt_template import StaleVersion


async def settings_in_session(session):
    row = await session.get(PersonalizationSettings, OWNER_SCOPE)
    if row is None:
        row = PersonalizationSettings()
        session.add(row)
        await session.flush()
    return row


async def settings():
    from db.accessors.user_preference import lock
    async with get_session_maker()() as session:
        await lock(session)
        row = await settings_in_session(session)
        await session.commit()
        return row


async def update_settings(expected_version, **changes):
    from db.accessors.user_preference import InvalidPreference, lock, revoke
    if not changes or set(changes) - {'use_preferences', 'suggest_preferences'} or any(type(v) is not bool for v in changes.values()) or changes.get('suggest_preferences'):
        raise InvalidPreference
    async with get_session_maker()() as session:
        await lock(session)
        row = await settings_in_session(session)
        if row.version != expected_version:
            raise StaleVersion
        if changes.get('use_preferences') is False:
            await revoke(session)
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        await session.commit()
        return row
