"""Explicit preference CRUD and exact historical revisions; never an agent tool."""
import json
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from db.accessors import user_preference as preferences, preference_revision, chat_context
from api.errors import refuse


class PrivatePreferenceRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private_handler(request):
            try:
                response = await handler(request)
                response.headers['Cache-Control'] = 'no-store'
                return response
            except (preferences.StaleVersion, preferences.PreferenceConflict):
                raise refuse(409, 'preference_conflict', 'Die Präferenzen wurden geändert oder die Grenze ist erreicht. Lade sie neu; je Feld und Geltungsbereich ist nur ein aktiver Wert möglich.') from None
            except (RequestValidationError, preferences.InvalidPreference):
                raise refuse(422, 'preference_invalid', 'Prüfe Feld, Konto und Wert (1–500 Zeichen).') from None
            except SQLAlchemyError:
                raise refuse(503, 'preferences_unavailable', 'Die Präferenzen sind gerade nicht erreichbar. Versuch es gleich noch einmal.') from None
        return private_handler


router = APIRouter(route_class=PrivatePreferenceRoute)
PreferenceKey = Literal['answer_length', 'salutation', 'signature']
PreferenceStatus = Literal['active', 'paused']


class PreferenceCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: PreferenceKey
    scope: str = Field(default='*', min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    status: PreferenceStatus = 'active'


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    scope: str | None = Field(default=None, min_length=1, max_length=100)
    value: str | None = Field(default=None, min_length=1, max_length=500)
    status: PreferenceStatus | None = None

    @model_validator(mode='after')
    def changes(self):
        fields = self.model_fields_set - {'expected_version'}
        if not fields or any(getattr(self, key) is None for key in fields):
            raise ValueError('preference_invalid')
        return self


class PreferenceOut(BaseModel):
    id: str
    key: PreferenceKey
    scope: str
    value: str
    status: PreferenceStatus
    version: int
    revision_id: str
    source: Literal['manual', 'confirmed_candidate'] = 'manual'
    confirmed_at: datetime


class HistoricalPreferenceOut(BaseModel):
    revision_id: str
    key: PreferenceKey | None = None
    scope: str | None = None
    value: str | None = None
    source: Literal['manual', 'confirmed_candidate'] = 'manual'
    confirmed_at: datetime | None = None
    removed: bool = True


class PreferenceContextOut(BaseModel):
    enabled: bool
    resolver_version: str
    revisions: list[HistoricalPreferenceOut]


async def output(row):
    if row is None:
        raise refuse(404, 'preference_unavailable', 'Diese Präferenz gibt es nicht mehr. Lade die Übersicht neu.')
    rev = (await preference_revision.get_revisions([row.revision_id]))[0]
    if rev is None or rev.removed:
        raise refuse(404, 'preference_unavailable', 'Diese Präferenz gibt es nicht mehr. Lade die Übersicht neu.')
    return PreferenceOut(id=row.id, key=row.key, scope=row.scope, value=rev.value, status=row.status,
                         version=row.version, revision_id=rev.id, source=rev.source, confirmed_at=rev.confirmed_at)


@router.get('', operation_id='preferences_list')
async def list_preferences() -> list[PreferenceOut]:
    return [await output(row) for row in await preferences.list_preferences()]


@router.post('', operation_id='preference_create', status_code=201)
async def create_preference(body: PreferenceCreate) -> PreferenceOut:
    return await output(await preferences.create(**body.model_dump()))


@router.patch('/{id}', operation_id='preference_update')
async def update_preference(id: str, body: PreferenceUpdate) -> PreferenceOut:
    return await output(await preferences.change(id, **body.model_dump(exclude_unset=True)))


@router.delete('/{id}', operation_id='preference_delete', status_code=204)
async def delete_preference(id: str, expected_version: int = Query(ge=1)) -> Response:
    if await preferences.change(id, expected_version, delete=True) is None:
        raise refuse(404, 'preference_unavailable', 'Diese Präferenz gibt es nicht mehr. Lade die Übersicht neu.')
    return Response(status_code=204)


@router.get('/contexts/{context_id}', operation_id='preference_context_get')
async def get_preference_context(context_id: str) -> PreferenceContextOut:
    context = await chat_context.get_context(context_id)
    if context is None:
        raise refuse(404, 'context_unavailable', 'Diese Unterhaltung ist nicht verfügbar.')
    ids = json.loads(context.preference_revision_ids_json)
    revisions = await preference_revision.get_revisions(ids)
    return PreferenceContextOut(enabled=context.preferences_enabled, resolver_version=context.preference_resolver_version,
        revisions=[HistoricalPreferenceOut(revision_id=id) if rev is None or rev.removed else
                   HistoricalPreferenceOut(revision_id=id, key=rev.key, scope=rev.scope, value=rev.value,
                                           source=rev.source, confirmed_at=rev.confirmed_at, removed=False)
                   for id, rev in zip(ids, revisions)])
