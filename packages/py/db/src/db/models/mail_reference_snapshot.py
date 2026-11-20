"""Owner-readable local mail retained when a legacy duplicate cannot be identified."""
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class MailReferenceSnapshot(SQLModel, table=True):
    __tablename__ = "mail_reference_snapshot"

    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="mail_account.id", ondelete="CASCADE", index=True)
    content_json: str = Field(sa_column=Column(Text, nullable=False))
