"""Server-owned opt-in; candidate suggestions remain unavailable."""
from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel
from db.models.prompt_template import OWNER_SCOPE


class PersonalizationSettings(SQLModel, table=True):
    __tablename__ = 'personalization_settings'
    __table_args__ = (CheckConstraint('NOT suggest_preferences'),)
    owner_scope: str = Field(default=OWNER_SCOPE, primary_key=True)
    use_preferences: bool = False
    suggest_preferences: bool = False
    version: int = 1
