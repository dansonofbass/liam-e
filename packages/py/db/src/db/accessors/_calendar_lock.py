"""Serialize calendar queue/lifecycle transactions before taking row locks."""

from sqlalchemy import text


async def lock_source(session, source_id: str) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                          {"key": f"calendar:{source_id}"})
