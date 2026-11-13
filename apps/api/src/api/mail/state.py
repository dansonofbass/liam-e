"""Presentation state derived from account, sync state and open jobs."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from db.models.mail_account import MailAccount


@dataclass
class AccountStatus:
    state: Literal["ok", "syncing", "auth_expired", "error", "never"]
    error_code: str
    last_sync_at: datetime | None


def account_status(account, sync_state, open_job) -> AccountStatus:
    error = sync_state.last_error if sync_state else ""
    if error and not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error):
        error = "provider_error"
    last_sync = sync_state.last_sync_at if sync_state else None
    if open_job and open_job.kind == "sync" and open_job.status in ("queued", "running"):
        status = "syncing"
    elif sync_state is None:
        status = "never"
    elif error == "auth_expired":
        status = "auth_expired"
    elif error or sync_state.status == "error":
        status = "error"
    else:
        status = "ok"
    return AccountStatus(status, error, last_sync)


def color_indexes(accounts: list[MailAccount]) -> dict[str, int]:
    return {a.id: i % 4 for i, a in enumerate(sorted(accounts, key=lambda a: (a.created_at, a.id)))}


def connection(account) -> Literal["connector", "oauth", "imap"]:
    if account.auth_type == "mistral_connector":
        return "connector"
    if account.auth_type == "oauth2":
        return "oauth"
    return "imap"
