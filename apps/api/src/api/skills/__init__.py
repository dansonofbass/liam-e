"""Server-side skill catalog, trusted tool registry, and turn execution runtime."""

from api.skills.catalog import BUILTIN_SKILLS, BuiltinSkillSpec, ensure_builtin_skills
from api.skills.registry import TOOL_REGISTRY, RegisteredTool, ToolRegistry
from api.skills.runtime import (
    check_tool_allowed,
    skill_prompt_message,
    tools_for_turn,
    validate_active_tools,
)
from api.skills.service import (
    create_skill,
    delete_skill,
    get_skill_detail,
    list_skills_with_revisions,
    resolve_skill,
    update_skill,
)
from api.skills.types import (
    ActiveSkill,
    SkillConflictError,
    SkillDisabledError,
    SkillError,
    SkillExecutionRef,
    SkillNotFoundError,
    SkillProtectedError,
    SkillRevisionUnavailableError,
    SkillToolUnavailableError,
    SkillToolUnknownError,
    SkillValidationError,
    SkillWorkflowStep,
    ToolOutcome,
)

__all__ = [
    "ActiveSkill",
    "BUILTIN_SKILLS",
    "BuiltinSkillSpec",
    "RegisteredTool",
    "SkillConflictError",
    "SkillDisabledError",
    "SkillError",
    "SkillExecutionRef",
    "SkillNotFoundError",
    "SkillProtectedError",
    "SkillRevisionUnavailableError",
    "SkillToolUnavailableError",
    "SkillToolUnknownError",
    "SkillValidationError",
    "SkillWorkflowStep",
    "TOOL_REGISTRY",
    "ToolOutcome",
    "ToolRegistry",
    "check_tool_allowed",
    "create_skill",
    "delete_skill",
    "ensure_builtin_skills",
    "get_skill_detail",
    "list_skills_with_revisions",
    "resolve_skill",
    "skill_prompt_message",
    "tools_for_turn",
    "update_skill",
    "validate_active_tools",
]
