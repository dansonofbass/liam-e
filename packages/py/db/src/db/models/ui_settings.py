"""The one installation-wide UI configuration; there is no per-request owner.

Like the prompt library, the owner is a deployment-level server constant (``OWNER_SCOPE``),
never a request identity: callers cannot choose or override it. The single row holds the
device-independent swipe assignment of the mail list; ``revision`` guards it against lost
updates from concurrent devices.
"""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from db.models._common import new_id, utc_datetime_column, utcnow

OWNER_SCOPE = "installation"


class UiSettings(SQLModel, table=True):
    __tablename__ = "ui_settings"
    __table_args__ = (
        UniqueConstraint("owner_scope", name="uq_ui_settings_owner_scope"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_scope: str = Field(default=OWNER_SCOPE)
    swipe_left: str
    swipe_right: str
    revision: int = 1
    updated_at: datetime = Field(default_factory=utcnow, sa_column=utc_datetime_column())
