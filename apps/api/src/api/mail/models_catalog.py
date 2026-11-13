"""Available chat models, cached briefly to avoid repeated catalogue requests."""
import logging
import time
from datetime import date, datetime, timezone

from pydantic import BaseModel
from env.mail import env as mail_env
from utils.mistral import mistral_client

logger = logging.getLogger(__name__)
MODEL_TEXTS = {
    'mistral-large-latest': ('Mistral Large', 'Für anspruchsvolle Aufgaben und ausführliche Antworten.'),
    'mistral-medium-latest': ('Mistral Medium', 'Für vielseitige Aufgaben im Alltag.'),
    'mistral-small-latest': ('Mistral Small', 'Für schnelle Antworten auf einfache Fragen.'),
    'magistral-medium-latest': ('Magistral Medium', 'Für Aufgaben, die mehr Nachdenken brauchen.'),
    'magistral-small-latest': ('Magistral Small', 'Für schnelles Nachdenken über einfache Aufgaben.'),
}
_cache = None
_cached_at = 0.0


class ChatModelOut(BaseModel):
    id: str
    label: str
    description: str
    is_default: bool


def reset_cache():
    global _cache, _cached_at
    _cache = None
    _cached_at = 0.0


def _model(id, default):
    label, description = MODEL_TEXTS.get(id, (' '.join(word.capitalize() for word in id.removesuffix('-latest').split('-')), ''))
    return ChatModelOut(id=id, label=label, description=description, is_default=id == default)


def _expired(value):
    if not value: return False
    if isinstance(value, datetime):
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value) < datetime.now(timezone.utc)
    if isinstance(value, date): return value < date.today()
    if isinstance(value, str):
        try: return date.fromisoformat(value[:10]) < date.today()
        except ValueError: return False
    return False


async def list_chat_models() -> list[ChatModelOut]:
    global _cache, _cached_at
    default = mail_env.mail_chat_model
    if _cache is not None and time.monotonic() - _cached_at < 600 and _cache[0].id == default:
        return list(_cache)
    try:
        response = await mistral_client().models.list_async()
        ids = {default}
        for card in response.data:
            capabilities = getattr(card, 'capabilities', None)
            if not capabilities or not getattr(capabilities, 'completion_chat', False) or not getattr(capabilities, 'function_calling', False) or _expired(getattr(card, 'deprecation', None)):
                continue
            id = getattr(card, 'id', None)
            if not isinstance(id, str): continue
            aliases = getattr(card, 'aliases', None)
            latest = next((alias for alias in aliases if isinstance(alias, str) and alias.endswith('-latest')), None) if isinstance(aliases, list) else None
            ids.add(id if id.endswith('-latest') else latest or id)
        models = [_model(default, default)] + sorted((_model(id, default) for id in ids if id != default), key=lambda m: m.label)
        _cache, _cached_at = models, time.monotonic()
        return list(models)
    except Exception as error:
        logger.warning('%s', type(error).__name__)
        return [_model(default, default)]
