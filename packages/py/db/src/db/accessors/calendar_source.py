"""Calendar source storage."""

from sqlalchemy import select

from db.engine import get_session_maker
from db.models.calendar_source import CalendarSource


async def get(source_id: str) -> CalendarSource | None:
    async with get_session_maker()() as session:
        return await session.get(CalendarSource, source_id)


async def list_active() -> list[CalendarSource]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(CalendarSource).where(CalendarSource.is_active.is_(True)).order_by(CalendarSource.id))).scalars())
