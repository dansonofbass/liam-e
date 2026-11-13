"""Shared account/credential plumbing for the mail feature.

Loads an account's decrypted credential payload, keeps OAuth tokens fresh (persisting refreshed
tokens back, encrypted), and verifies IMAP logins before an account is stored.
"""

from __future__ import annotations

import asyncio
import imaplib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from db.accessors import mail_account as account_access
from db.accessors import mail_credential as credential_access
from db.models.mail_account import MailAccount

from api.mail import crypto, providers, secrets


class CredentialError(RuntimeError):
    """Raised when an account has no usable stored credential."""


def credential_kind(account: MailAccount) -> str:
    return "oauth2_tokens" if account.auth_type == "oauth2" else "imap_password"


async def upsert_account(
    *, provider: str, auth_type: str, email_address: str
) -> MailAccount:
    """Find the account by email or create it; re-connecting refreshes provider/auth_type."""
    account = await account_access.get_account_by_email(email_address)
    if account is None:
        return await account_access.create_account(
            provider=provider,
            auth_type=auth_type,
            email_address=email_address,
            display_name=email_address,
        )
    account.provider = provider
    account.auth_type = auth_type
    account.is_active = True
    return await account_access.touch_account(account)


async def load_credentials(account: MailAccount) -> dict[str, Any]:
    token = await credential_access.load_credential(
        account.id, credential_kind(account)
    )
    if token is None:
        raise CredentialError(
            f"Account {account.email_address} has no stored credential"
        )
    return crypto.decrypt_payload(token)


async def imap_password(credentials: dict[str, Any]) -> str:
    """The IMAP/SMTP password: stored directly, or resolved from a workspace secret by name.

    Only the secret's *name* is ever stored in ``mail_credential``; the value is resolved here on
    each use, so rotating the secret in Mistral Studio needs no reconnect.
    """
    if credentials.get("password"):
        return str(credentials["password"])
    secret_name = credentials.get("password_secret")
    if secret_name:
        return await secrets.resolve_workspace_secret(str(secret_name))
    raise CredentialError(
        "The stored credential has neither 'password' nor 'password_secret'"
    )


async def save_tokens(account: MailAccount, tokens: dict[str, Any]) -> None:
    await credential_access.store_credential(
        account_id=account.id,
        kind="oauth2_tokens",
        encrypted_payload=crypto.encrypt_payload(tokens),
    )


async def valid_access_token(account: MailAccount, tokens: dict[str, Any]) -> str:
    """A non-expired access token, refreshing (and persisting) it when necessary."""
    if (
        tokens.get("access_token")
        and time.time() < int(tokens.get("expires_at", 0)) - 60
    ):
        return tokens["access_token"]
    if not tokens.get("refresh_token"):
        raise CredentialError(
            f"Account {account.email_address} has no refresh token; reconnect it via OAuth"
        )
    refreshed = await providers.refresh_access_token(
        account.provider, refresh_token=tokens["refresh_token"]
    )
    await save_tokens(account, refreshed)
    return refreshed["access_token"]


def verify_imap_login(
    *, email_address: str, password: str, host: str, port: int, use_ssl: bool = True
) -> None:
    """Blocking login check; raises (imaplib.IMAP4.error) when the credentials are rejected.

    Runs in a worker thread via ``asyncio.to_thread`` — never call it on the event loop.
    """
    connection = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    try:
        connection.login(email_address, password)
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            logger.debug("IMAP logout after the login check failed", exc_info=True)


async def check_imap_login(**kwargs: Any) -> None:
    await asyncio.to_thread(verify_imap_login, **kwargs)
