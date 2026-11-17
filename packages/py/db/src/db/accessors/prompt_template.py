"""Serialized prompt mutations with immutable revisions and atomic revocation.

Deployment access is restricted externally to one owner. OWNER_SCOPE is not an
assertion about gateway authentication and is never derived from request data.
"""
from hashlib import sha256
from sqlalchemy import select, update
from db.engine import get_session_maker
from db.models.prompt_template import OWNER_SCOPE, PromptTemplate
from db.models.prompt_revision import PromptRevision
from db.models.chat_conversation import ChatConversation
from db.models.chat_context import ChatContext


class StaleVersion(Exception):
    """The caller's expected version no longer matches."""


def revision(template_id: str, number: int, content: str) -> PromptRevision:
    return PromptRevision(template_id=template_id, number=number, content=content,
                          content_hash=sha256(content.encode()).hexdigest())


async def list_templates() -> list[PromptTemplate]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(PromptTemplate).where(
            PromptTemplate.owner_scope == OWNER_SCOPE).order_by(PromptTemplate.name))).scalars())


async def get_template(template_id: str) -> PromptTemplate | None:
    async with get_session_maker()() as session:
        row = await session.get(PromptTemplate, template_id)
        return row if row and row.owner_scope == OWNER_SCOPE else None


async def create_template(name: str, content: str) -> PromptTemplate:
    async with get_session_maker()() as session:
        row = PromptTemplate(name=name, revision_id="")
        rev = revision(row.id, 1, content)
        row.revision_id = rev.id
        session.add_all([row, rev])
        await session.commit()
        return row


async def change_template(template_id: str, expected_version: int, *, name: str | None = None,
                          content: str | None = None, delete: bool = False) -> PromptTemplate | None:
    async with get_session_maker()() as session:
        row = (await session.execute(select(PromptTemplate).where(
            PromptTemplate.id == template_id, PromptTemplate.owner_scope == OWNER_SCOPE
        ).with_for_update())).scalar_one_or_none()
        if row is None:
            return None
        if row.version != expected_version:
            raise StaleVersion
        revisions = select(PromptRevision.id).where(PromptRevision.template_id == row.id)
        if delete:
            await session.execute(update(ChatContext).where(ChatContext.prompt_revision_id.in_(revisions))
                                  .values(revoked=True, prompt_hash=None))
            await session.execute(update(ChatConversation).where(ChatConversation.prompt_revision_id.in_(revisions))
                                  .values(prompt_revision_id=None, version=ChatConversation.version + 1))
            await session.execute(update(PromptRevision).where(PromptRevision.template_id == row.id)
                                  .values(content=None, content_hash=None, removed=True))
            await session.delete(row)
        else:
            previous = await session.get(PromptRevision, row.revision_id)
            if (content is None or content == previous.content) and (name is None or name == row.name):
                return row  # Nothing changes: no new revision and no version bump.
            row.version += 1
            rev = revision(row.id, row.version, content if content is not None else previous.content)
            row.revision_id = rev.id
            if name is not None:
                row.name = name
            session.add(rev)
        await session.commit()
        return row
