"""Serialized skill mutations, builtin catalog sync, and context revocation.

Advisory lock ``380084`` serializes builtin catalog seeding/upgrades alongside
explicit per-row ``FOR UPDATE`` locks matching template/conversation ordering.
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.accessors.prompt_template import StaleVersion
from db.engine import get_session_maker
from db.models.chat_context import ChatContext
from db.models.prompt_template import OWNER_SCOPE
from db.models.skill_definition import SkillDefinition
from db.models.skill_revision import SkillRevision

MAX_CUSTOM_SKILLS = 50
BUILTIN_SYNC_LOCK_KEY = 380084


class DuplicateSkillSlug(Exception):
    """Another skill already uses this slug in the installation."""


class BuiltinSkillProtected(Exception):
    """Built-in skills cannot be deleted or structurally altered via user CRUD."""


class SkillQuotaExceeded(Exception):
    """Maximum number of stored custom skills has been reached."""


def compute_content_hash(
    *,
    slug: str,
    name: str,
    description: str,
    instructions: str,
    workflow_steps_json: str,
    allowed_tools_json: str,
) -> str:
    """Compute a stable SHA-256 digest over the canonical skill definition."""
    payload = json.dumps(
        {
            "slug": slug,
            "name": name,
            "description": description,
            "instructions": instructions,
            "workflow_steps": json.loads(workflow_steps_json),
            "allowed_tools": json.loads(allowed_tools_json),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def build_revision(
    *,
    skill_id: str,
    number: int,
    slug: str,
    name: str,
    description: str,
    instructions: str,
    workflow_steps_json: str,
    allowed_tools_json: str,
) -> SkillRevision:
    """Construct an immutable skill revision with its canonical content hash."""
    return SkillRevision(
        skill_id=skill_id,
        number=number,
        slug=slug,
        name=name,
        description=description,
        instructions=instructions,
        workflow_steps_json=workflow_steps_json,
        allowed_tools_json=allowed_tools_json,
        content_hash=compute_content_hash(
            slug=slug,
            name=name,
            description=description,
            instructions=instructions,
            workflow_steps_json=workflow_steps_json,
            allowed_tools_json=allowed_tools_json,
        ),
    )


async def _revoke_contexts_in_session(
    session: AsyncSession,
    skill_id: str,
    *,
    clear_hash: bool = False,
) -> None:
    """Revoke any turn contexts bound to revisions of ``skill_id``."""
    skill_column = getattr(ChatContext, "skill_revision_id", None)
    if skill_column is None:
        return
    revision_ids = select(SkillRevision.id).where(SkillRevision.skill_id == skill_id)
    values: dict[str, object] = {"revoked": True}
    if clear_hash and hasattr(ChatContext, "skill_hash"):
        values["skill_hash"] = None
    await session.execute(
        update(ChatContext).where(skill_column.in_(revision_ids)).values(**values)
    )


async def list_skills() -> list[SkillDefinition]:
    """List all skill definitions in the installation scope ordered by origin and name."""
    async with get_session_maker()() as session:
        rows = (await session.execute(
            select(SkillDefinition)
            .where(SkillDefinition.owner_scope == OWNER_SCOPE)
            .order_by(SkillDefinition.origin, SkillDefinition.name, SkillDefinition.slug)
        )).scalars()
        return list(rows)


async def get_skill(identifier: str) -> SkillDefinition | None:
    """Look up a skill by UUID id or stable slug."""
    async with get_session_maker()() as session:
        row = await session.get(SkillDefinition, identifier)
        if row and row.owner_scope == OWNER_SCOPE:
            return row
        stmt = select(SkillDefinition).where(
            SkillDefinition.owner_scope == OWNER_SCOPE,
            SkillDefinition.slug == identifier,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def create_custom_skill(
    *,
    slug: str,
    name: str,
    description: str,
    instructions: str,
    workflow_steps_json: str,
    allowed_tools_json: str,
    status: str = "active",
) -> SkillDefinition:
    """Create a new custom skill and its initial immutable revision."""
    async with get_session_maker()() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": BUILTIN_SYNC_LOCK_KEY})
        existing_count = int((await session.execute(
            select(func.count()).select_from(SkillDefinition).where(
                SkillDefinition.owner_scope == OWNER_SCOPE,
                SkillDefinition.origin == "custom",
            )
        )).scalar_one())
        if existing_count >= MAX_CUSTOM_SKILLS:
            raise SkillQuotaExceeded
        row = SkillDefinition(
            slug=slug,
            origin="custom",
            status=status,
            name=name,
            description=description,
            version=1,
            revision_id="",
            updated_at=datetime.now(timezone.utc),
        )
        rev = build_revision(
            skill_id=row.id,
            number=1,
            slug=slug,
            name=name,
            description=description,
            instructions=instructions,
            workflow_steps_json=workflow_steps_json,
            allowed_tools_json=allowed_tools_json,
        )
        row.revision_id = rev.id
        session.add_all([row, rev])
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise DuplicateSkillSlug from error
        return row


async def change_skill(
    identifier: str,
    expected_version: int,
    *,
    name: str | None = None,
    description: str | None = None,
    instructions: str | None = None,
    workflow_steps_json: str | None = None,
    allowed_tools_json: str | None = None,
    status: str | None = None,
    delete: bool = False,
) -> SkillDefinition | None:
    """Update, toggle status, or delete a skill with optimistic concurrency and revocation."""
    async with get_session_maker()() as session:
        row = (await session.execute(
            select(SkillDefinition).where(
                SkillDefinition.owner_scope == OWNER_SCOPE,
                (SkillDefinition.id == identifier) | (SkillDefinition.slug == identifier),
            ).with_for_update()
        )).scalar_one_or_none()
        if row is None:
            return None
        if row.version != expected_version:
            raise StaleVersion
        if row.origin == "builtin":
            if delete or any(
                value is not None
                for value in (name, description, instructions, workflow_steps_json, allowed_tools_json)
            ):
                raise BuiltinSkillProtected
            if status is None or status == row.status:
                return row
            previous = await session.get(SkillRevision, row.revision_id)
            assert previous is not None
            row.version += 1
            row.status = status
            row.updated_at = datetime.now(timezone.utc)
            if status == "disabled":
                await _revoke_contexts_in_session(session, row.id)
            await session.commit()
            return row

        if delete:
            await _revoke_contexts_in_session(session, row.id, clear_hash=True)
            await session.execute(
                update(SkillRevision).where(SkillRevision.skill_id == row.id).values(
                    slug=None,
                    name=None,
                    description=None,
                    instructions=None,
                    workflow_steps_json=None,
                    allowed_tools_json=None,
                    content_hash=None,
                    removed=True,
                )
            )
            await session.delete(row)
            await session.commit()
            return row

        previous = await session.get(SkillRevision, row.revision_id)
        assert previous is not None
        next_name = row.name if name is None else name
        next_description = row.description if description is None else description
        next_instructions = previous.instructions if instructions is None else instructions
        next_steps = previous.workflow_steps_json if workflow_steps_json is None else workflow_steps_json
        next_tools = previous.allowed_tools_json if allowed_tools_json is None else allowed_tools_json
        next_status = row.status if status is None else status

        content_changed = (
            next_name != row.name
            or next_description != row.description
            or next_instructions != previous.instructions
            or next_steps != previous.workflow_steps_json
            or next_tools != previous.allowed_tools_json
        )
        status_changed = next_status != row.status
        if not content_changed and not status_changed:
            return row

        old_tools = set(json.loads(previous.allowed_tools_json or "[]"))
        new_tools = set(json.loads(next_tools or "[]"))
        tools_narrowed = bool(old_tools - new_tools)

        row.version += 1
        row.updated_at = datetime.now(timezone.utc)
        row.name = next_name
        row.description = next_description
        row.status = next_status
        if content_changed:
            max_number = int((await session.execute(
                select(func.coalesce(func.max(SkillRevision.number), 0)).where(SkillRevision.skill_id == row.id)
            )).scalar_one())
            rev = build_revision(
                skill_id=row.id,
                number=max_number + 1,
                slug=row.slug,
                name=next_name,
                description=next_description,
                instructions=next_instructions or "",
                workflow_steps_json=next_steps or "[]",
                allowed_tools_json=next_tools or "[]",
            )
            row.revision_id = rev.id
            session.add(rev)
        if next_status == "disabled" or tools_narrowed:
            await _revoke_contexts_in_session(session, row.id)
        await session.commit()
        return row


async def sync_builtin_skills(specs: Sequence[dict[str, str]]) -> list[SkillDefinition]:
    """Idempotently create or upgrade built-in skills while preserving owner status."""
    if not specs:
        return []
    synced: list[SkillDefinition] = []
    async with get_session_maker()() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": BUILTIN_SYNC_LOCK_KEY})
        now = datetime.now(timezone.utc)
        for spec in specs:
            slug = spec["slug"]
            target_hash = compute_content_hash(
                slug=slug,
                name=spec["name"],
                description=spec["description"],
                instructions=spec["instructions"],
                workflow_steps_json=spec["workflow_steps_json"],
                allowed_tools_json=spec["allowed_tools_json"],
            )
            existing = (await session.execute(
                select(SkillDefinition).where(
                    SkillDefinition.owner_scope == OWNER_SCOPE,
                    SkillDefinition.slug == slug,
                ).with_for_update()
            )).scalar_one_or_none()
            if existing is None:
                row = SkillDefinition(
                    slug=slug,
                    origin="builtin",
                    status="active",
                    name=spec["name"],
                    description=spec["description"],
                    version=1,
                    revision_id="",
                    updated_at=now,
                )
                rev = build_revision(
                    skill_id=row.id,
                    number=1,
                    slug=slug,
                    name=spec["name"],
                    description=spec["description"],
                    instructions=spec["instructions"],
                    workflow_steps_json=spec["workflow_steps_json"],
                    allowed_tools_json=spec["allowed_tools_json"],
                )
                row.revision_id = rev.id
                session.add_all([row, rev])
                synced.append(row)
                continue

            if existing.origin != "builtin":
                synced.append(existing)
                continue
            current_rev = await session.get(SkillRevision, existing.revision_id)
            if current_rev and not current_rev.removed and current_rev.content_hash == target_hash:
                synced.append(existing)
                continue

            old_tools = set(json.loads(current_rev.allowed_tools_json or "[]")) if current_rev else set()
            new_tools = set(json.loads(spec["allowed_tools_json"]))
            if old_tools - new_tools:
                await _revoke_contexts_in_session(session, existing.id)
            max_number = int((await session.execute(
                select(func.coalesce(func.max(SkillRevision.number), 0)).where(SkillRevision.skill_id == existing.id)
            )).scalar_one())
            existing.version += 1
            existing.name = spec["name"]
            existing.description = spec["description"]
            existing.updated_at = now
            rev = build_revision(
                skill_id=existing.id,
                number=max_number + 1,
                slug=slug,
                name=spec["name"],
                description=spec["description"],
                instructions=spec["instructions"],
                workflow_steps_json=spec["workflow_steps_json"],
                allowed_tools_json=spec["allowed_tools_json"],
            )
            existing.revision_id = rev.id
            session.add(rev)
            synced.append(existing)
        await session.commit()
    return synced
