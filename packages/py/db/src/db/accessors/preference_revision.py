"""Read exact revisions, never replace a missing historical value with today's value."""
from sqlalchemy import select
from db.engine import get_session_maker
from db.models.preference_revision import PreferenceRevision
from db.models.prompt_template import OWNER_SCOPE


async def get_revisions(ids):
    if not ids:
        return []
    async with get_session_maker()() as session:
        rows = (await session.execute(select(PreferenceRevision).where(
            PreferenceRevision.id.in_(ids), PreferenceRevision.owner_scope == OWNER_SCOPE))).scalars()
        by_id = {row.id: row for row in rows}
        return [by_id.get(id) for id in ids]
