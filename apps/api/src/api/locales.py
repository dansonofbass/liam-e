"""The supported output languages in the API."""

from typing import Literal

from db.accessors import ui_settings

Locale = Literal["de", "en"]
DEFAULT_LOCALE: Locale = "en"


async def resolve_locale(browser_hint: Locale = DEFAULT_LOCALE) -> Locale:
    """Respect the installation setting even when a client has stale UI state."""
    settings = await ui_settings.get_or_create()
    if settings.locale == "de":
        return "de"
    if settings.locale == "en":
        return "en"
    return browser_hint
