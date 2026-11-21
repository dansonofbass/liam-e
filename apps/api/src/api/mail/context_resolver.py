"""Resolve one immutable turn context; no prompt text enters metadata or errors."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from db.accessors import chat_context, chat_settings
from sqlalchemy.exc import SQLAlchemyError
from db.accessors.prompt_template import StaleVersion
from api.errors import refuse
from api.mail.agent_prompt import APP_PROMPT_VERSION
from api.skills import TOOL_REGISTRY, ensure_builtin_skills


async def resolve_context(*, conversation_id=None, text, model=None, prompt_revision_id=None,
                          skill_id=None, skill_revision_id=None,
                          account_id=None, context_message_id=None, context_occurrence_id=None, expected_mail_scope_version=None, calendar_source_ids=None, calendar_timezone='UTC',
                          task_source='none', task_source_account_id=None, without_preferences=False, **_):
    try:
        ZoneInfo(calendar_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise refuse(422, 'context_invalid', 'Die Zeitzone ist ungültig.') from None
    try:
        registered_tool_names = None
        if skill_id is not None or skill_revision_id is not None:
            await ensure_builtin_skills()
            # Pass server-implemented tool names across the db/api package boundary so missing
            # tools fail closed before persistence; the turn still executes only revision.allowed_tools.
            registered_tool_names = {tool.name for tool in TOOL_REGISTRY.list_tools()}
        return await chat_context.resolve(conversation_id=conversation_id, title=' '.join(text.split())[:60],
                                          model=model, revision_id=prompt_revision_id, account_id=account_id,
                                          app_prompt_version=APP_PROMPT_VERSION, calendar_source_ids=calendar_source_ids,
                                          context_message_id=context_message_id, context_occurrence_id=context_occurrence_id, expected_mail_scope_version=expected_mail_scope_version,
                                          task_source=task_source, task_source_account_id=task_source_account_id,
                                          without_preferences=without_preferences,
                                          skill_id=skill_id, skill_revision_id=skill_revision_id,
                                          registered_tool_names=registered_tool_names)
    except chat_context.SkillNotFound:
        raise refuse(404, 'skill_not_found', 'Dieser Skill existiert nicht mehr. Wähle einen anderen.') from None
    except chat_context.SkillRevisionUnavailable:
        raise refuse(404, 'skill_revision_unavailable', 'Diese Skill-Version ist nicht mehr verfügbar.') from None
    except chat_context.SkillDisabled:
        raise refuse(409, 'skill_disabled', 'Dieser Skill ist deaktiviert. Aktiviere ihn zuerst oder wähle einen anderen.') from None
    except chat_context.SkillToolUnavailable:
        raise refuse(422, 'skill_tool_unavailable', 'Ein für diesen Skill benötigtes Werkzeug steht in dieser Version nicht zur Verfügung.') from None
    except chat_context.PreferencesUnavailable:
        raise refuse(503, 'preferences_unavailable', 'Die Präferenzen konnten nicht geladen werden. Du kannst ausdrücklich ohne Präferenzen fortfahren.') from None
    except chat_context.CalendarReferenceUnavailable:
        raise refuse(404, 'calendar_reference_unavailable', 'Dieser Termin ist für den Chat nicht mehr verfügbar.') from None
    except chat_context.ContextUnavailable:
        raise refuse(404, 'context_unavailable', 'Die Unterhaltung oder Vorlage ist nicht verfügbar. Starte eine neue Unterhaltung.') from None
    except chat_context.ScopeChange:
        raise refuse(409, 'conversation_scope_change_requires_new', 'Für andere Konten, Kalender oder Aufgaben brauchst du eine neue Unterhaltung. Der bisherige Verlauf bleibt erhalten.') from None
    except StaleVersion:
        raise refuse(409, 'version_conflict', 'Die Auswahl wurde inzwischen geändert. Versuch es noch einmal.') from None
    except chat_settings.GrantsChanged:
        raise refuse(409, 'chat_settings_changed', 'Die Kontofreigaben haben sich geändert. Prüfe die aktuelle Auswahl.') from None
    except chat_settings.AccountNotGranted:
        raise refuse(403, 'chat_account_not_granted', 'Dieses Mailkonto ist für den Chat nicht freigegeben. Prüfe die Chat-Einstellungen.') from None
    except SQLAlchemyError:
        raise refuse(503, 'settings_unavailable', 'Die Chat-Freigaben sind gerade nicht erreichbar.') from None
    except ValueError:
        raise refuse(422, 'context_invalid', 'Die Auswahl ist ungültig. Prüfe das Konto und die freigegebenen Kalender; ändere die Vorlage einer bestehenden Unterhaltung über ihre Einstellungen.') from None
