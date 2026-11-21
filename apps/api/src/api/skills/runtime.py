"""Turn-scoped skill execution helpers: prompt envelope, tool filtering, and guards."""

from __future__ import annotations

import json
from typing import Any

from api.skills.registry import TOOL_REGISTRY, ToolRegistry
from api.skills.types import ActiveSkill, SkillToolUnavailableError


def skill_prompt_message(skill: ActiveSkill) -> dict[str, str]:
    """Build the user-role workflow envelope for an active skill.

    Skill instructions and step descriptions never become system/app rules: they
    stay strictly subordinate to fixed app rules, scopes, and confirmation cards.
    """
    payload = {
        "skill": {
            "id": skill.id,
            "slug": skill.slug,
            "name": skill.name,
            "version": skill.version,
            "revision_id": skill.revision_id,
            "description": skill.description,
            "allowed_tools": list(skill.allowed_tools),
            "workflow_steps": [step.model_dump() for step in skill.workflow_steps],
            "instructions": skill.instructions,
        },
        "runtime_rules": (
            "Dieser Skill ist nur für den aktuellen Turn aktiv. "
            "App-Regeln, freigegebene Konto-/Kalender-/Aufgabenbereiche und Bestätigungskarten haben stets Vorrang. "
            "Es stehen ausschließlich die in allowed_tools genannten Werkzeuge zur Verfügung."
        ),
    }
    return {
        "role": "user",
        "content": (
            "Aktiver Skill für diesen Turn (Ablaufvorgabe, nachrangig zu App-Regeln und Bestätigungspflichten):\n"
            + json.dumps(payload, ensure_ascii=False)
        ),
    }


def tools_for_turn(
    skill: ActiveSkill | None,
    *,
    registry: ToolRegistry = TOOL_REGISTRY,
) -> list[dict[str, Any]]:
    """Return the exact Mistral tool schemas allowed for this turn."""
    if skill is None:
        return registry.base_schemas()
    return registry.schemas_for(skill.allowed_tools)


def check_tool_allowed(
    tool_name: str,
    allowed_tools: tuple[str, ...] | None,
    *,
    registry: ToolRegistry = TOOL_REGISTRY,
) -> str | None:
    """Return an error code if ``tool_name`` is unknown, unavailable, or outside turn permission."""
    tool = registry.get(tool_name)
    if allowed_tools is not None:
        if tool_name not in allowed_tools:
            return "tool_not_permitted" if tool is not None else "unknown_tool"
        if tool is None:
            return "skill_tool_unavailable"
        return None
    if tool is None:
        return "unknown_tool"
    if tool.skill_only:
        return "tool_not_permitted"
    return None


def validate_active_tools(
    skill: ActiveSkill,
    *,
    registry: ToolRegistry = TOOL_REGISTRY,
) -> None:
    """Fail closed if any tool required by ``skill`` is missing from ``registry``."""
    try:
        registry.resolve_for_execution(skill.allowed_tools)
    except SkillToolUnavailableError:
        raise
