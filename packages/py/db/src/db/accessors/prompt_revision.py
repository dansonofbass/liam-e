"""Read immutable revisions within the installation owner scope."""
from sqlalchemy import select
from db.engine import get_session_maker
from db.models.prompt_revision import PromptRevision
from db.models.prompt_template import OWNER_SCOPE


async def list_revisions(template_id: str) -> list[PromptRevision]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(PromptRevision).where(
            PromptRevision.template_id == template_id,
            PromptRevision.owner_scope == OWNER_SCOPE,
            PromptRevision.removed.is_(False),
        ).order_by(PromptRevision.number.desc()))).scalars())


async def get_revision(revision_id: str) -> PromptRevision | None:
    async with get_session_maker()() as session:
        row = await session.get(PromptRevision, revision_id)
        return row if row and row.owner_scope == OWNER_SCOPE else None
