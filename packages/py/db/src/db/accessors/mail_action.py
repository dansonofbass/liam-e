"""Record and atomically consume undoable actions."""

from datetime import datetime

from sqlalchemy import delete, select, update

from db.engine import get_session_maker
from db.models.mail_action import MailAction


async def record(*, message_id: str, account_id: str, kind: str, previous_json: str) -> MailAction:
    row = MailAction(message_id=message_id, account_id=account_id, kind=kind, previous_json=previous_json)
    async with get_session_maker()() as session:
        session.add(row)
        await session.commit()
        return row


async def get_many(ids: list[str]) -> list[MailAction]:
    async with get_session_maker()() as session:
        return list((await session.execute(select(MailAction).where(MailAction.id.in_(ids)))).scalars().all())


async def mark_undone(action_id: str, at: datetime) -> bool:
    async with get_session_maker()() as session:
        result = await session.execute(update(MailAction).where(MailAction.id == action_id, MailAction.undone_at.is_(None)).values(undone_at=at).returning(MailAction.id))
        changed = result.scalar_one_or_none() is not None
        await session.commit()
        return changed


async def delete_for_account(account_id: str) -> None:
    async with get_session_maker()() as session:
        await session.execute(delete(MailAction).where(MailAction.account_id == account_id))
        await session.commit()
