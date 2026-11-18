"""Independent server-owned opt-ins and the latest suggestion activation boundary."""
from datetime import datetime
from db.models._common import utc_datetime_column
from sqlmodel import Field, SQLModel
from db.models.prompt_template import OWNER_SCOPE


class PersonalizationSettings(SQLModel, table=True):
    __tablename__ = 'personalization_settings'
    owner_scope: str = Field(default=OWNER_SCOPE, primary_key=True)
    use_preferences: bool = False
    suggest_preferences: bool = False
    version: int = 1
    suggestion_activation: str | None = None
    suggestion_activated_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
