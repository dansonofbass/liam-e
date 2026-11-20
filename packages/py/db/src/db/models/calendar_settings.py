"""The installation owner's preferred target for new calendar proposals."""
from sqlmodel import Field, SQLModel

from db.models.prompt_template import OWNER_SCOPE


class CalendarSettings(SQLModel, table=True):
    __tablename__ = "calendar_settings"

    owner_scope: str = Field(default=OWNER_SCOPE, primary_key=True)
    # Keep the choice visible if this source disappears. Its ID is never reassigned.
    default_source_id: str | None = None
    version: int = 1
