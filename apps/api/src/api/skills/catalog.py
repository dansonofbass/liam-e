"""Built-in server-registered skill catalog and idempotent DB synchronization."""

from __future__ import annotations

from dataclasses import dataclass
import json

from db.accessors import skill_definition as skill_access
from db.models.skill_definition import SkillDefinition

from api.skills.registry import TOOL_REGISTRY
from api.skills.types import SkillWorkflowStep


@dataclass(frozen=True)
class BuiltinSkillSpec:
    """Declarative code-owned skill registered into the installation catalog."""

    slug: str
    name: str
    description: str
    instructions: str
    workflow_steps: tuple[SkillWorkflowStep, ...]
    allowed_tools: tuple[str, ...]

    def to_sync_record(self) -> dict[str, str]:
        tools = TOOL_REGISTRY.validate_for_definition(self.allowed_tools)
        allowed_set = set(tools)
        for step in self.workflow_steps:
            missing = set(step.tool_names) - allowed_set
            if missing:
                raise ValueError(f"Step {step.id} references tools outside allowed_tools: {sorted(missing)}")
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "workflow_steps_json": json.dumps(
                [step.model_dump() for step in self.workflow_steps],
                ensure_ascii=False,
            ),
            "allowed_tools_json": json.dumps(tools, ensure_ascii=False),
        }


BUILTIN_SKILLS: tuple[BuiltinSkillSpec, ...] = (
    BuiltinSkillSpec(
        slug="daily_briefing",
        name="Tagesüberblick",
        description="Führt freigegebene Termine, fällige Aufgaben und bekannte Mailfristen für einen Tag strukturiert zusammen.",
        instructions=(
            "Führe den Tagesüberblick in klaren Schritten aus:\n"
            "1. Rufe zuerst collect_daily_briefing für das gewünschte lokale Datum (Standard: heute) auf.\n"
            "2. Lies bei Bedarf einzelne Termine, Aufgabenserien oder wichtige Frist-Mails gezielt mit "
            "get_calendar_occurrence, get_task, get_message oder get_insights nach.\n"
            "3. Gliedere die Antwort getrennt nach Terminen, Aufgaben und Mailfristen. Benenne ausgeschlossene, "
            "pausierte, veraltete oder unvollständige Bereiche aus coverage ausdrücklich und behaupte bei "
            "fehlender Abdeckung niemals, es sei nichts fällig. Zeige relevante Mails mit show_mails und "
            "biete bis zu drei knappe Folgeaktionen über suggest_followups an.\n"
            "4. Wenn der Nutzer eine Aufgabenänderung ausdrücklich verlangt, schlage sie ausschließlich über "
            "propose_task zur Bestätigung vor; führe niemals Aktionen ohne Bestätigung aus."
        ),
        workflow_steps=(
            SkillWorkflowStep(
                id="collect_agenda",
                title="Domänendaten einsammeln",
                description="Termine, fällige/überfällige Aufgaben und bekannte Mailfristen über collect_daily_briefing abrufen.",
                tool_names=["collect_daily_briefing"],
            ),
            SkillWorkflowStep(
                id="inspect_details",
                title="Details nachlesen",
                description="Bei offenen Rückfragen oder unvollständigen Serien gezielt Einzelheiten im freigegebenen Umfang nachlesen.",
                tool_names=["get_calendar_occurrence", "get_task", "get_message", "get_insights"],
            ),
            SkillWorkflowStep(
                id="summarize_and_propose",
                title="Überblick ausgeben und optional vorschlagen",
                description="Getrennt nach Domänen mit Abdeckungshinweisen antworten, Mails/Folgeaktionen zeigen und Aufgabenänderungen nur per propose_task vorschlagen.",
                tool_names=["show_mails", "suggest_followups", "propose_task"],
            ),
        ),
        allowed_tools=(
            "collect_daily_briefing",
            "get_calendar_occurrence",
            "get_task",
            "get_message",
            "get_insights",
            "show_mails",
            "suggest_followups",
            "propose_task",
        ),
    ),
)


async def ensure_builtin_skills() -> list[SkillDefinition]:
    """Synchronize built-in skill definitions into the DB without overriding owner status."""
    records = [spec.to_sync_record() for spec in BUILTIN_SKILLS]
    return await skill_access.sync_builtin_skills(records)
