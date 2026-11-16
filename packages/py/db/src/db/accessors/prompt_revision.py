"""Read immutable revisions within the installation owner scope."""
from db.engine import get_session_maker
from db.models.prompt_revision import PromptRevision
from db.models.prompt_template import OWNER_SCOPE


async def get_revision(revision_id: str) -> PromptRevision | None:
    async with get_session_maker()() as session:
        row = await session.get(PromptRevision, revision_id)
        return row if row and row.owner_scope == OWNER_SCOPE else None
