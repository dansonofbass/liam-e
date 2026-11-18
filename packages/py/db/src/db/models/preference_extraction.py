"""Content-free durable claims: an extraction is never retried after claiming."""
from sqlmodel import Field, SQLModel


class PreferenceExtraction(SQLModel, table=True):
    __tablename__ = 'preference_extraction'
    source_message_id: str = Field(primary_key=True)
    extractor_version: int = Field(primary_key=True)
    activation: str
