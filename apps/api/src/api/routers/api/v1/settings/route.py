"""Sectioned settings contract; UI swipe settings remain on their existing route."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator
from db.accessors import user_preference
from api.routers.api.v1.preferences.route import PrivatePreferenceRoute

router = APIRouter(route_class=PrivatePreferenceRoute)


class PersonalizationOut(BaseModel):
    use_preferences: bool
    suggest_preferences: bool
    version: int


class SettingsOut(BaseModel):
    personalization: PersonalizationOut


class PersonalizationUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    use_preferences: bool | None = None
    suggest_preferences: bool | None = None

    @model_validator(mode='after')
    def changes(self):
        fields = self.model_fields_set - {'expected_version'}
        if not fields or any(getattr(self, key) is None for key in fields) or self.suggest_preferences:
            raise ValueError('preference_invalid')
        return self


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    personalization: PersonalizationUpdate


def output(row):
    return SettingsOut(personalization=PersonalizationOut.model_validate(row, from_attributes=True))


@router.get('', operation_id='settings_get')
async def get_settings() -> SettingsOut:
    return output(await user_preference.settings())


@router.patch('', operation_id='settings_update')
async def update_settings(body: SettingsUpdate) -> SettingsOut:
    return output(await user_preference.update_settings(**body.personalization.model_dump(exclude_unset=True)))
