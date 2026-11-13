"""Accessor for ``mail_credential`` rows. Payloads arrive and leave already encrypted."""

from sqlalchemy import select

from db.engine import get_session_maker
from db.models._common import utcnow
from db.models.mail_credential import MailCredential


async def store_credential(
    *, account_id: str, kind: str, encrypted_payload: str
) -> MailCredential:
    """Insert or replace the credential of one (account, kind)."""
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailCredential).where(
                MailCredential.account_id == account_id, MailCredential.kind == kind
            )
        )
        credential = result.scalar_one_or_none()
        if credential is None:
            credential = MailCredential(
                account_id=account_id, kind=kind, encrypted_payload=encrypted_payload
            )
        else:
            credential.encrypted_payload = encrypted_payload
            credential.updated_at = utcnow()
        session.add(credential)
        await session.commit()
        return credential


async def load_credential(account_id: str, kind: str) -> str | None:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailCredential).where(
                MailCredential.account_id == account_id, MailCredential.kind == kind
            )
        )
        credential = result.scalar_one_or_none()
        return credential.encrypted_payload if credential is not None else None


async def delete_for_account(account_id: str) -> None:
    async with get_session_maker()() as session:
        result = await session.execute(
            select(MailCredential).where(MailCredential.account_id == account_id)
        )
        for credential in result.scalars().all():
            await session.delete(credential)
        await session.commit()
