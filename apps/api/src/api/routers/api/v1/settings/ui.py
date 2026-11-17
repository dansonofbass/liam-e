"""UI settings contract: a server-owned scope, validated actions, revision-guarded updates.

The owner is the fixed installation scope of the single-user deployment, never a request
identity: the body cannot name or override it (unknown fields are refused, not ignored). GET
initializes the canonical configuration exactly once, so a second device reads the same
confirmed assignment. PATCH validates the action allowlist and swaps on ``expected_revision``;
a concurrent change answers 409 with the way to reload instead of winning silently.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError

from api.errors import refuse
from db.accessors import ui_settings


class PrivateSettingsRoute(APIRoute):
    """Validation failures name the problem without echoing the rejected payload."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except SQLAlchemyError:
                raise refuse(503, 'settings_unavailable', 'Die Einstellungen sind gerade nicht erreichbar. Versuch es gleich noch einmal.') from None
            except RequestValidationError:
                raise refuse(422, 'ui_settings_invalid', 'Prüfe die Angaben: Jede Richtung erlaubt „Keine Aktion“, „Archivieren“, „Gelesen/Ungelesen“ und „In den Papierkorb“, und eine Änderung braucht mindestens eine davon. Eigentümer lassen sich nicht mitgeben.') from None
        return private_handler


router = APIRouter(route_class=PrivateSettingsRoute, responses={
    409: {'description': 'Expected revision is stale'},
    422: {'description': 'Invalid fields; the rejected payload is not echoed'},
})

SwipeAction = Literal['none', 'archive', 'toggle_read', 'trash']


class UiSettingsOut(BaseModel):
    swipe_left: SwipeAction
    swipe_right: SwipeAction
    revision: int
    updated_at: datetime


class UiSettingsUpdate(BaseModel):
    """A change to the swipe assignment; the owner scope is not part of the contract."""

    model_config = ConfigDict(extra='forbid')

    expected_revision: int = Field(ge=1)
    swipe_left: SwipeAction | None = None
    swipe_right: SwipeAction | None = None

    @model_validator(mode='after')
    def require_explicit_change(self):
        if any(getattr(self, key) is None for key in ('swipe_left', 'swipe_right') if key in self.model_fields_set):
            raise ValueError('ui_settings_invalid')
        if self.swipe_left is None and self.swipe_right is None:
            raise ValueError('ui_settings_invalid')
        return self


@router.get('', operation_id='settings_ui_get')
async def get_ui_settings() -> UiSettingsOut:
    """The one confirmed assignment, initializing the canonical defaults on first read."""
    row = await ui_settings.get_or_create()
    return UiSettingsOut.model_validate(row, from_attributes=True)


@router.patch('', operation_id='settings_ui_update')
async def update_ui_settings(body: UiSettingsUpdate) -> UiSettingsOut:
    """Apply a validated change while the caller holds the current revision."""
    try:
        row = await ui_settings.update(body.expected_revision, swipe_left=body.swipe_left, swipe_right=body.swipe_right)
    except ui_settings.StaleRevision:
        raise refuse(409, 'ui_settings_conflict', 'Die Einstellungen wurden inzwischen geändert. Lade sie neu und nimm deine Auswahl dann bewusst auf.') from None
    return UiSettingsOut.model_validate(row, from_attributes=True)
