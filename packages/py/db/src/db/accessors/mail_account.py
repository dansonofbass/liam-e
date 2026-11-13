"""Accessor for ``mail_account`` rows: the only place that reads or writes them."""

from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.mail_account import MailAccount


async def list_accounts(session: AsyncSession | None = None) -> list[MailAccount]:
    async def run(s: AsyncSession) -> list[MailAccount]:
        result = await s.execute(select(MailAccount).order_by(MailAccount.created_at))
        return list(result.scalars().all())

    if session is not None:
        return await run(session)
    async with get_session_maker()() as s:
        return await run(s)


async def get_account(account_id: str) -> MailAccount | None:
    async with get_session_maker()() as session:
        return await session.get(MailAccount, account_id)


async def get_account_by_email(email_address: str) -> MailAccount | None:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailAccount)
            .where(func.lower(MailAccount.email_address) == email_address.lower())
            .order_by(MailAccount.created_at, MailAccount.id)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def create_account(
    *, provider: str, auth_type: str, email_address: str, display_name: str = ""
) -> MailAccount:
    async with get_session_maker()() as session:
        account = MailAccount(
            provider=provider,
            auth_type=auth_type,
            email_address=email_address,
            display_name=display_name,
        )
        session.add(account)
        await session.commit()
        return account


async def touch_account(account: MailAccount) -> MailAccount:
    account.updated_at = utcnow()
    async with get_session_maker()() as session:
        session.add(account)
        await session.commit()
        return account


async def update_display_name(account_id: str, display_name: str) -> MailAccount | None:
    async with get_session_maker()() as session:
        account = await session.get(MailAccount, account_id)
        if account is None:
            return None
        account.display_name = display_name
        account.updated_at = utcnow()
        session.add(account)
        await session.commit()
        return account


async def delete_account(account_id: str) -> bool:
    async with get_session_maker()() as session:
        account = await session.get(MailAccount, account_id)
        if account is None:
            return False
        await session.delete(account)
        await session.commit()
        return True
