"""Shared helpers for the contributed model modules.

Private on purpose (underscore): the ``db.models`` loader skips underscore modules, so this is
imported directly by the model modules that need it and registers no table itself.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy.types import DateTime


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc_datetime_column(**kwargs: Any) -> Any:
    """A timezone-aware timestamp column, the one datetime shape every model uses."""
    return Column(DateTime(timezone=True), **kwargs)
