"""Owner-managed default chat model for new conversations."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from api.errors import quiet_validation_route, refuse
from api.mail.models_catalog import (
    DefaultModelStatus,
    default_model_state,
    list_chat_models,
    require_available_model,
)
from db.accessors import chat_model_settings
from db.accessors.prompt_template import StaleVersion

router = APIRouter(route_class=quiet_validation_route("chat_model_settings_invalid", "Prüfe die Modellauswahl."))


class ChatModelSettingsOut(BaseModel):
    version: int
    default_model: str | None
    effective_default_model: str
    app_default_model: str
    status: DefaultModelStatus


class ChatModelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    default_model: str | None


async def _output(row) -> ChatModelSettingsOut:
    state = await default_model_state(row.default_model, include_models=False)
    return ChatModelSettingsOut(
        version=row.version,
        default_model=state.default_model,
        effective_default_model=state.effective_default_model,
        app_default_model=state.app_default_model,
        status=state.status,
    )


@router.get("", operation_id="chat_model_settings_get")
async def get_chat_model_settings() -> ChatModelSettingsOut:
    try:
        return await _output(await chat_model_settings.get())
    except SQLAlchemyError:
        raise refuse(503, "settings_unavailable", "Die Einstellungen sind gerade nicht erreichbar.") from None


@router.patch("", operation_id="chat_model_settings_update")
async def update_chat_model_settings(body: ChatModelSettingsUpdate) -> ChatModelSettingsOut:
    try:
        current = await chat_model_settings.get()
    except SQLAlchemyError:
        raise refuse(503, "settings_unavailable", "Die Einstellungen sind gerade nicht erreichbar.") from None
    if current.version != body.expected_version:
        raise refuse(409, "version_conflict", "Das Standardmodell wurde inzwischen geändert. Lade die Einstellungen erneut.")
    if body.default_model is not None:
        require_available_model(body.default_model, await list_chat_models())
    try:
        row = await chat_model_settings.update(body.expected_version, body.default_model)
        return await _output(row)
    except StaleVersion:
        raise refuse(409, "version_conflict", "Das Standardmodell wurde inzwischen geändert. Lade die Einstellungen erneut.") from None
    except SQLAlchemyError:
        raise refuse(503, "settings_unavailable", "Die Einstellungen sind gerade nicht erreichbar.") from None
