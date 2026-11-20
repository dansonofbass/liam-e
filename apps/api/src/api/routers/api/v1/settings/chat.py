"""Owner-managed chat access to connected mail accounts."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from api.errors import quiet_validation_route, refuse
from db.accessors import chat_settings
from db.accessors.prompt_template import StaleVersion

router = APIRouter(route_class=quiet_validation_route("chat_settings_invalid", "Prüfe die Kontoauswahl."))


class ChatSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_ids: list[str]
    version: int


class ChatSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    account_ids: list[str]


@router.get("", operation_id="chat_settings_get")
async def get_chat_settings() -> ChatSettingsOut:
    try:
        return ChatSettingsOut.model_validate(await chat_settings.get())
    except SQLAlchemyError:
        raise refuse(503, "settings_unavailable", "Die Einstellungen sind gerade nicht erreichbar.") from None


@router.patch("", operation_id="chat_settings_update")
async def update_chat_settings(body: ChatSettingsUpdate) -> ChatSettingsOut:
    try:
        row = await chat_settings.update(body.expected_version, body.account_ids)
        return ChatSettingsOut.model_validate(row)
    except StaleVersion:
        raise refuse(409, "version_conflict", "Die Freigaben wurden inzwischen geändert. Lade sie erneut.") from None
    except chat_settings.AccountNotGranted:
        raise refuse(422, "chat_settings_invalid", "Mindestens ein Konto ist nicht verbunden oder sein Studio-Postfach wurde noch nicht durch eine Synchronisierung bestätigt.") from None
    except SQLAlchemyError:
        raise refuse(503, "settings_unavailable", "Die Einstellungen sind gerade nicht erreichbar.") from None
