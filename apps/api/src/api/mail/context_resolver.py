"""Resolve one immutable turn context; no prompt text enters metadata or errors."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from db.accessors import chat_context
from db.accessors.prompt_template import StaleVersion
from api.errors import refuse
from api.mail.agent_prompt import APP_PROMPT_VERSION


async def resolve_context(*, conversation_id=None, text, model=None, prompt_revision_id=None,
                          account_id=None, calendar_source_ids=None, calendar_timezone='UTC', **_):
    try:
        ZoneInfo(calendar_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise refuse(422, 'context_invalid', 'Die Zeitzone ist ungültig.') from None
    try:
        return await chat_context.resolve(conversation_id=conversation_id, title=' '.join(text.split())[:60],
                                          model=model, revision_id=prompt_revision_id, account_id=account_id,
                                          app_prompt_version=APP_PROMPT_VERSION, calendar_source_ids=calendar_source_ids)
    except chat_context.ContextUnavailable:
        raise refuse(404, 'context_unavailable', 'Die Unterhaltung oder Vorlage ist nicht verfügbar. Starte eine neue Unterhaltung.') from None
    except chat_context.ScopeChange:
        raise refuse(409, 'conversation_scope_change_requires_new', 'Für andere Konten oder Kalender brauchst du eine neue Unterhaltung. Der bisherige Verlauf bleibt erhalten.') from None
    except StaleVersion:
        raise refuse(409, 'version_conflict', 'Die Auswahl wurde inzwischen geändert. Versuch es noch einmal.') from None
    except ValueError:
        raise refuse(422, 'context_invalid', 'Die Auswahl ist ungültig. Prüfe das Konto und die freigegebenen Kalender; ändere die Vorlage einer bestehenden Unterhaltung über ihre Einstellungen.') from None
