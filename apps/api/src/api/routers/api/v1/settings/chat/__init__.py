"""Owner-managed chat settings: account permissions and default model."""
from fastapi import params

from .route import (
    ChatSettingsOut,
    ChatSettingsUpdate,
    get_chat_settings,
    router,
    update_chat_settings,
)

dependencies: tuple[params.Depends, ...] = ()

__all__ = [
    "ChatSettingsOut",
    "ChatSettingsUpdate",
    "dependencies",
    "get_chat_settings",
    "router",
    "update_chat_settings",
]
