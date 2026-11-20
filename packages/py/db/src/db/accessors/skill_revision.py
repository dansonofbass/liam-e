"""Read immutable skill revisions within the installation owner scope."""

from sqlalchemy import select

from db.engine import get_session_maker
from db.models.prompt_template import OWNER_SCOPE
from db.models.skill_revision import SkillRevision


async def list_revisions(skill_id: str) -> list[SkillRevision]:
    """List active (non-removed) revisions of one skill, newest first."""
    async with get_session_maker()() as session:
        return list((await session.execute(select(SkillRevision).where(
            SkillRevision.skill_id == skill_id,
            SkillRevision.owner_scope == OWNER_SCOPE,
            SkillRevision.removed.is_(False),
        ).order_by(SkillRevision.number.desc()))).scalars())


async def get_revision(revision_id: str) -> SkillRevision | None:
    """Fetch a single skill revision in the installation owner scope."""
    async with get_session_maker()() as session:
        row = await session.get(SkillRevision, revision_id)
        return row if row and row.owner_scope == OWNER_SCOPE else None
