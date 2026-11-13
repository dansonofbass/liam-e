"""Inbox overview across connected accounts."""

from datetime import datetime
from typing import Literal

from db.accessors import mail_account, mail_job, mail_message, mail_sync_state
from fastapi import APIRouter
from pydantic import BaseModel

from api.mail import newsletters, state

router = APIRouter()


class AccountSummaryOut(BaseModel):
    id: str
    display_name: str
    email_address: str
    provider: str
    connection: Literal["connector", "oauth", "imap"]
    color_index: int
    unread: int
    state: Literal["ok", "syncing", "auth_expired", "error", "never"]
    error_code: str
    last_sync_at: datetime | None


class MailSummaryOut(BaseModel):
    unread_total: int
    accounts: list[AccountSummaryOut]
    last_sync_at: datetime | None
    newsletter_senders: int


async def account_summary(account, colors: dict[str, int], unread: dict[str, int]) -> AccountSummaryOut:
    sync_state = await mail_sync_state.get_state(account.id)
    job = await mail_job.latest_for_account(account.id, kind="sync", open_only=True)
    status = state.account_status(account, sync_state, job)
    return AccountSummaryOut(id=account.id, display_name=account.display_name, email_address=account.email_address, provider=account.provider, connection=state.connection(account), color_index=colors[account.id], unread=unread.get(account.id, 0), state=status.state, error_code=status.error_code, last_sync_at=status.last_sync_at)


@router.get("", operation_id="mail_summary")
async def mail_summary() -> MailSummaryOut:
    """Return unread inbox counts and sync status for all connected accounts."""
    accounts = await mail_account.list_accounts()
    colors = state.color_indexes(accounts)
    unread = await mail_message.count_unread(folder="INBOX")
    summaries = [await account_summary(a, colors, unread) for a in accounts]
    dates = [a.last_sync_at for a in summaries if a.last_sync_at is not None]
    return MailSummaryOut(unread_total=sum(a.unread for a in summaries), accounts=summaries, last_sync_at=max(dates, default=None), newsletter_senders=len(await newsletters.find_newsletters()))
