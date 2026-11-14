"""Access insights by message."""

import json
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from db.engine import get_session_maker
from db.models.mail_insight import MailInsight
from db.models.mail_message import MailMessage


def seed_row(*, id: str, message_id: str, points: list[str], deadline: date, followups: list[str]) -> MailInsight:
    """Construct an insight with a stable ID for the local seed transaction."""
    return MailInsight(id=id, message_id=message_id, points_json=json.dumps(points), deadline=deadline,
                       needs_reply=True, followups_json=json.dumps(followups), model="mistral-small-latest")


async def get(message_id: str) -> MailInsight | None:
    async with get_session_maker()() as session:
        return (await session.execute(select(MailInsight).where(MailInsight.message_id == message_id))).scalar_one_or_none()


async def get_for_messages(ids: list[str]) -> dict[str, MailInsight]:
    async with get_session_maker()() as session:
        rows = (await session.execute(select(MailInsight).where(MailInsight.message_id.in_(ids)))).scalars().all()
        return {row.message_id: row for row in rows}


async def upsert(message_id: str, *, points: list[str], deadline: date | None, needs_reply: bool, followups: list[str], model: str) -> MailInsight:
    row = MailInsight(message_id=message_id, points_json=json.dumps(points), deadline=deadline, needs_reply=needs_reply, followups_json=json.dumps(followups), model=model)
    values = dict(points_json=row.points_json, deadline=deadline, needs_reply=needs_reply, followups_json=row.followups_json, model=model)
    stmt = insert(MailInsight).values(**row.model_dump()).on_conflict_do_update(index_elements=[MailInsight.message_id], set_=values).returning(MailInsight)
    async with get_session_maker()() as session:
        result = (await session.execute(stmt)).scalar_one()
        await session.commit()
        return result


async def delete_for_account(account_id: str) -> None:
    async with get_session_maker()() as session:
        await session.execute(delete(MailInsight).where(MailInsight.message_id.in_(select(MailMessage.id).where(MailMessage.account_id == account_id))))
        await session.commit()
