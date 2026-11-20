"""Serialize transcription for the one owner of this app database."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text

from db.engine import get_session_maker


@asynccontextmanager
async def transcription_slot() -> AsyncIterator[bool]:
    """Release the transient lock on completion, cancellation, or connection loss."""
    async with get_session_maker()() as session, session.begin():
        acquired = await session.scalar(text("SELECT pg_try_advisory_xact_lock(380027)"))
        yield acquired is True
