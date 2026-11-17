"""Prompt CRUD; user content is never interpolated or logged."""
from datetime import datetime
from fastapi import APIRouter, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from db.accessors import prompt_template, prompt_revision
from api.errors import refuse

class PrivateContentRoute(APIRoute):
    """Validation failures must not echo the rejected template text."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except SQLAlchemyError:
                raise refuse(503, 'prompts_unavailable', 'Die Vorlagen sind gerade nicht erreichbar. Versuch es gleich noch einmal.') from None
            except RequestValidationError:
                raise refuse(422, 'prompt_invalid', 'Prüfe die Vorlage: Name 1–80 Zeichen, Text 1–8.000 Zeichen und eine gültige Version.') from None
        return private_handler


router = APIRouter(route_class=PrivateContentRoute, responses={
    404: {'description': 'Template unavailable'},
    409: {'description': 'Expected version is stale'},
    422: {'description': 'Invalid fields; user content is not echoed'},
})


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=8000)


class PromptUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    text: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode='after')
    def reject_null_content(self):
        if any(getattr(self, key) is None for key in ('name', 'text') if key in self.model_fields_set):
            raise ValueError('prompt_invalid')
        return self


class PromptOut(BaseModel):
    id: str
    name: str
    version: int
    revision_id: str
    text: str
    content_hash: str
    updated_at: datetime | None


class PromptRevisionOut(BaseModel):
    id: str
    number: int
    content: str
    content_hash: str


class PromptDetailOut(PromptOut):
    revisions: list[PromptRevisionOut]


async def output(row) -> PromptOut:
    if row is None:
        raise refuse(404, 'prompt_unavailable', 'Diese Vorlage gibt es nicht mehr. Wähle eine andere.')
    revision = await prompt_revision.get_revision(row.revision_id)
    if revision is None or revision.removed:
        raise refuse(404, 'prompt_unavailable', 'Diese Vorlage gibt es nicht mehr. Wähle eine andere.')
    return PromptOut(id=row.id, name=row.name, version=row.version, revision_id=revision.id,
                     text=revision.content, content_hash=revision.content_hash, updated_at=row.updated_at)


@router.get('', operation_id='prompts_list')
async def list_prompts() -> list[PromptOut]:
    return [await output(row) for row in await prompt_template.list_templates()]


@router.post('', operation_id='prompt_create', status_code=201)
async def create_prompt(body: PromptCreate) -> PromptOut:
    return await output(await prompt_template.create_template(body.name, body.text))


@router.get('/{id}', operation_id='prompt_get')
async def get_prompt(id: str) -> PromptDetailOut:
    current = await output(await prompt_template.get_template(id))
    revisions = await prompt_revision.list_revisions(id)
    if not revisions:
        raise refuse(404, 'prompt_unavailable', 'Diese Vorlage gibt es nicht mehr. Wähle eine andere.')
    return PromptDetailOut(**current.model_dump(), revisions=[
        PromptRevisionOut.model_validate(revision, from_attributes=True) for revision in revisions
    ])


@router.patch('/{id}', operation_id='prompt_update')
async def update_prompt(id: str, body: PromptUpdate) -> PromptOut:
    try:
        row = await prompt_template.change_template(id, body.expected_version, name=body.name, content=body.text)
    except prompt_template.StaleVersion:
        raise refuse(409, 'version_conflict', 'Die Vorlage wurde inzwischen geändert. Lade sie neu.') from None
    return await output(row)


@router.delete('/{id}', operation_id='prompt_delete', status_code=204)
async def delete_prompt(id: str, expected_version: int = Query(ge=1)) -> Response:
    try:
        row = await prompt_template.change_template(id, expected_version, delete=True)
    except prompt_template.StaleVersion:
        raise refuse(409, 'version_conflict', 'Die Vorlage wurde inzwischen geändert. Lade sie neu.') from None
    if row is None:
        raise refuse(404, 'prompt_unavailable', 'Diese Vorlage gibt es nicht mehr. Lade die Übersicht neu.')
    return Response(status_code=204)
