"""Isolated tests for the server-side tool registry, skill catalog, and runtime guards."""

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock

import pytest

from api.skills import (
    BUILTIN_SKILLS,
    RegisteredTool,
    SkillDisabledError,
    SkillNotFoundError,
    SkillProtectedError,
    SkillRevisionUnavailableError,
    SkillToolUnavailableError,
    SkillToolUnknownError,
    SkillValidationError,
    SkillWorkflowStep,
    TOOL_REGISTRY,
    ToolOutcome,
    ToolRegistry,
    check_tool_allowed,
    create_skill,
    delete_skill,
    resolve_skill,
    skill_prompt_message,
    tools_for_turn,
    update_skill,
)
from db.accessors import skill_definition as skill_access
from db.accessors import skill_revision as revision_access
from db.models.skill_definition import SkillDefinition
from db.models.skill_revision import SkillRevision

pytestmark = pytest.mark.anyio


@pytest.fixture
def skill_store(monkeypatch):
    """Isolated in-memory skill store without touching shared test helpers."""
    skills: dict[str, SkillDefinition] = {}
    revisions: dict[str, SkillRevision] = {}
    revoked_contexts: list[str] = []

    async def sync_builtin(specs):
        out = []
        now = datetime.now(timezone.utc)
        for spec in specs:
            existing = next((s for s in skills.values() if s.slug == spec["slug"]), None)
            if existing is None:
                row = SkillDefinition(
                    slug=spec["slug"],
                    origin="builtin",
                    status="active",
                    name=spec["name"],
                    description=spec["description"],
                    version=1,
                    revision_id="",
                    updated_at=now,
                )
                rev = skill_access.build_revision(
                    skill_id=row.id,
                    number=1,
                    slug=spec["slug"],
                    name=spec["name"],
                    description=spec["description"],
                    instructions=spec["instructions"],
                    workflow_steps_json=spec["workflow_steps_json"],
                    allowed_tools_json=spec["allowed_tools_json"],
                )
                row.revision_id = rev.id
                skills[row.id] = row
                revisions[rev.id] = rev
                out.append(row)
            else:
                out.append(existing)
        return out

    async def list_skills():
        return sorted(skills.values(), key=lambda s: (s.origin, s.name, s.slug))

    async def get_skill(identifier: str):
        if identifier in skills:
            return skills[identifier]
        return next((s for s in skills.values() if s.slug == identifier), None)

    async def create_custom(**kw):
        if any(s.slug == kw["slug"] for s in skills.values()):
            raise skill_access.DuplicateSkillSlug
        row = SkillDefinition(
            slug=kw["slug"],
            origin="custom",
            status=kw["status"],
            name=kw["name"],
            description=kw["description"],
            version=1,
            revision_id="",
            updated_at=datetime.now(timezone.utc),
        )
        rev = skill_access.build_revision(
            skill_id=row.id,
            number=1,
            slug=kw["slug"],
            name=kw["name"],
            description=kw["description"],
            instructions=kw["instructions"],
            workflow_steps_json=kw["workflow_steps_json"],
            allowed_tools_json=kw["allowed_tools_json"],
        )
        row.revision_id = rev.id
        skills[row.id] = row
        revisions[rev.id] = rev
        return row

    async def change_skill(identifier: str, expected_version: int, *, delete: bool = False, **changes):
        row = await get_skill(identifier)
        if row is None:
            return None
        if row.version != expected_version:
            raise skill_access.StaleVersion
        if row.origin == "builtin":
            if delete or any(
                changes.get(k) is not None
                for k in ("name", "description", "instructions", "workflow_steps_json", "allowed_tools_json")
            ):
                raise skill_access.BuiltinSkillProtected
            if changes.get("status") in (None, row.status):
                return row
            row.version += 1
            row.status = changes["status"]
            row.updated_at = datetime.now(timezone.utc)
            if row.status == "disabled":
                revoked_contexts.extend(r.id for r in revisions.values() if r.skill_id == row.id)
            return row
        if delete:
            for r in revisions.values():
                if r.skill_id == row.id:
                    revoked_contexts.append(r.id)
                    r.removed = True
                    r.slug = r.name = r.description = r.instructions = None
                    r.workflow_steps_json = r.allowed_tools_json = r.content_hash = None
            skills.pop(row.id)
            return row
        prev = revisions[row.revision_id]
        next_name = row.name if changes.get("name") is None else changes["name"]
        next_desc = row.description if changes.get("description") is None else changes["description"]
        next_instr = prev.instructions if changes.get("instructions") is None else changes["instructions"]
        next_steps = prev.workflow_steps_json if changes.get("workflow_steps_json") is None else changes["workflow_steps_json"]
        next_tools = prev.allowed_tools_json if changes.get("allowed_tools_json") is None else changes["allowed_tools_json"]
        next_status = row.status if changes.get("status") is None else changes["status"]
        old_tools = set(json.loads(prev.allowed_tools_json or "[]"))
        new_tools = set(json.loads(next_tools or "[]"))
        row.version += 1
        row.name = next_name
        row.description = next_desc
        row.status = next_status
        row.updated_at = datetime.now(timezone.utc)
        next_num = max(r.number for r in revisions.values() if r.skill_id == row.id) + 1
        rev = skill_access.build_revision(
            skill_id=row.id,
            number=next_num,
            slug=row.slug,
            name=next_name,
            description=next_desc,
            instructions=next_instr or "",
            workflow_steps_json=next_steps or "[]",
            allowed_tools_json=next_tools or "[]",
        )
        row.revision_id = rev.id
        revisions[rev.id] = rev
        if next_status == "disabled" or (old_tools - new_tools):
            revoked_contexts.extend(r.id for r in revisions.values() if r.skill_id == row.id)
        return row

    monkeypatch.setattr(skill_access, "sync_builtin_skills", sync_builtin)
    monkeypatch.setattr(skill_access, "list_skills", list_skills)
    monkeypatch.setattr(skill_access, "get_skill", get_skill)
    monkeypatch.setattr(skill_access, "create_custom_skill", create_custom)
    monkeypatch.setattr(skill_access, "change_skill", change_skill)
    monkeypatch.setattr(revision_access, "get_revision", AsyncMock(side_effect=lambda id: revisions.get(id)))
    monkeypatch.setattr(
        revision_access,
        "list_revisions",
        AsyncMock(side_effect=lambda sid: sorted((r for r in revisions.values() if r.skill_id == sid and not r.removed), key=lambda r: -r.number)),
    )
    return skills, revisions, revoked_contexts


def test_base_tools_never_expose_skill_only_tools():
    base_names = {tool["function"]["name"] for tool in TOOL_REGISTRY.base_schemas()}
    assert "collect_daily_briefing" not in base_names
    assert {"search_messages", "search_calendar", "search_tasks", "create_draft", "propose_task"} <= base_names
    assert check_tool_allowed("collect_daily_briefing", None) == "tool_not_permitted"
    assert check_tool_allowed("unknown_arbitrary_exec", None) == "unknown_tool"


def test_registry_rejects_unregistered_tools_on_definition_and_execution():
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            name="safe_read",
            kind="read",
            description="Read",
            parameters={"type": "object", "properties": {}},
            handler=AsyncMock(return_value=ToolOutcome("{}")),
        )
    )
    assert registry.validate_for_definition(["safe_read", "safe_read"]) == ["safe_read"]
    with pytest.raises(SkillToolUnknownError) as missing:
        registry.validate_for_definition(["safe_read", "shell_exec"])
    assert missing.value.missing == ["shell_exec"]

    with pytest.raises(SkillToolUnavailableError) as unavailable:
        registry.resolve_for_execution(["safe_read", "removed_tool"])
    assert unavailable.value.missing == ["removed_tool"]


async def test_builtin_daily_briefing_resolves_and_filters_tools_strictly(skill_store):
    assert await resolve_skill() is None
    active = await resolve_skill(skill_id="daily_briefing")
    assert active is not None
    assert active.slug == "daily_briefing"
    assert active.origin == "builtin"
    assert [step.id for step in active.workflow_steps] == ["collect_agenda", "inspect_details", "summarize_and_propose"]

    tool_names = {tool["function"]["name"] for tool in tools_for_turn(active)}
    assert tool_names == set(BUILTIN_SKILLS[0].allowed_tools)
    assert "collect_daily_briefing" in tool_names
    assert "create_draft" not in tool_names
    assert check_tool_allowed("collect_daily_briefing", active.allowed_tools) is None
    assert check_tool_allowed("create_draft", active.allowed_tools) == "tool_not_permitted"

    envelope = skill_prompt_message(active)
    assert envelope["role"] == "user"
    assert "nachrangig zu App-Regeln" in envelope["content"]
    assert "collect_daily_briefing" in envelope["content"]


async def test_unknown_disabled_missing_tool_and_deleted_skills_fail_cleanly(skill_store):
    skills, revisions, revoked = skill_store
    with pytest.raises(SkillNotFoundError):
        await resolve_skill(skill_id="does_not_exist")

    # Disable builtin skill -> explicit activation refuses cleanly and marks contexts for revocation
    row, _ = await update_skill("daily_briefing", 1, status="disabled")
    assert row.status == "disabled" and row.revision_id in revoked
    with pytest.raises(SkillDisabledError):
        await resolve_skill(skill_id="daily_briefing")

    # Cannot delete or mutate instructions of builtin skill
    with pytest.raises(SkillProtectedError):
        await delete_skill("daily_briefing", 2)
    with pytest.raises(SkillProtectedError):
        await update_skill("daily_briefing", 2, instructions="Override")

    # Custom skill creation validates registered tools & workflow consistency
    with pytest.raises(SkillToolUnknownError):
        await create_skill(
            slug="bad_skill",
            name="Bad",
            description="Invalid tool",
            instructions="Test",
            workflow_steps=[],
            allowed_tools=["not_a_real_tool"],
        )
    with pytest.raises(SkillValidationError):
        await create_skill(
            slug="step_mismatch",
            name="Mismatch",
            description="Step uses unlisted tool",
            instructions="Test",
            workflow_steps=[SkillWorkflowStep(id="s1", title="Step 1", description="Run", tool_names=["search_messages"])],
            allowed_tools=["list_accounts"],
        )

    custom, first_rev = await create_skill(
        slug="inbox_triage",
        name="Inbox triage",
        description="Summarize unread inbox items",
        instructions="Read unread inbox mails only.",
        workflow_steps=[SkillWorkflowStep(id="scan", title="Scan", description="Search unread mails", tool_names=["search_messages"])],
        allowed_tools=["search_messages", "get_message"],
    )
    resolved = await resolve_skill(skill_id=custom.slug)
    assert resolved is not None and resolved.revision_id == first_rev.id

    # Simulate an older stored revision whose tool was removed in a newer code release
    first_rev.allowed_tools_json = json.dumps(["legacy_removed_tool"])
    with pytest.raises(SkillToolUnavailableError):
        await resolve_skill(skill_revision_id=first_rev.id)

    # Restore tools, narrow via update, then delete -> tombstones and revokes
    first_rev.allowed_tools_json = json.dumps(["get_message", "search_messages"])
    updated, second_rev = await update_skill(custom.id, 1, allowed_tools=["search_messages"])
    assert updated.version == 2 and first_rev.id in revoked
    assert second_rev.id != first_rev.id

    await delete_skill(custom.id, 2)
    assert custom.id not in skills
    assert revisions[second_rev.id].removed is True
    assert revisions[second_rev.id].instructions is None
    with pytest.raises(SkillRevisionUnavailableError):
        await resolve_skill(skill_revision_id=second_rev.id)
