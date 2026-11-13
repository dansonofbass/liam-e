"""Mail account management: list, connect (OAuth2 or IMAP app password), delete, sync.

Credentials are stored encrypted (``api.mail.crypto``) and never returned by any endpoint.
"""

import imaplib
from datetime import datetime
from typing import Annotated, Any, Literal

import httpx
from db.accessors import mail_account as account_access
from db.accessors import mail_credential as credential_access
from db.accessors import mail_message as message_access
from db.accessors import mail_sync_state as sync_state_access
from db.models.mail_account import MailAccount
from env.mail import env as mail_env
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from api.errors import refuse
from api.mail import crypto, providers, secrets, transport
from api.mail.netguard import BlockedAddressError
from api.mail import sync as sync_service
from api.mail.service import AccountConflictError, check_imap_login, upsert_account

router = APIRouter()


class AccountOut(BaseModel):
    id: str
    provider: str
    auth_type: str
    email_address: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, account: MailAccount) -> "AccountOut":
        return cls(
            id=account.id,
            provider=account.provider,
            auth_type=account.auth_type,
            email_address=account.email_address,
            display_name=account.display_name,
            is_active=account.is_active,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )


class ImapConnectRequest(BaseModel):
    email_address: str
    password: str = Field(
        default="",
        description="IMAP app password (e.g. iCloud/Yahoo app-specific password). Exactly one of password / password_secret.",
    )
    password_secret: str = Field(
        default="",
        description=(
            "Name of a Mistral workspace secret holding the app password (lowercase, e.g. "
            "'yahoo-app-password') — one secret per account. Only the reference is stored."
        ),
    )
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_starttls: bool = False

    @model_validator(mode="after")
    def _exactly_one_password(self) -> "ImapConnectRequest":
        if bool(self.password) == bool(self.password_secret):
            raise ValueError(
                "Genau eines von 'password' oder 'password_secret' angeben."
            )
        return self


class OAuthAuthorizeOut(BaseModel):
    authorization_url: str
    state: str


class SyncOut(BaseModel):
    status: str
    synced: int
    cursor: str
    error_code: str = ""


def _redirect_base(request: Request) -> str:
    return (
        mail_env.mail_oauth_redirect_base_url or str(request.base_url).rstrip("/")
    ).rstrip("/")


@router.get(
    "", operation_id="mail_accounts_list", summary="List all connected mail accounts"
)
async def list_accounts() -> list[AccountOut]:
    """List all connected mail accounts with provider, auth type and e-mail address.

    Credentials are never part of the response.
    """
    accounts = await account_access.list_accounts()
    return [AccountOut.from_model(a) for a in accounts]


@router.post(
    "/imap",
    operation_id="mail_account_connect_imap",
    status_code=201,
    summary="Connect an IMAP/SMTP account",
)
async def connect_imap(body: ImapConnectRequest) -> AccountOut:
    """Connect an IMAP/SMTP account with an app password and store its credentials encrypted.

    Exactly one of ``password`` or ``password_secret`` is required; ``password_secret`` names a
    workspace secret (for example ``yahoo-app-password``) whose value is resolved now and re-read
    at runtime, so only the reference is stored. Server hosts must be allow-listed and the IMAP
    login is checked before the account is created; answers 201 with the new account.
    An address already using another connection type answers 409 without changing credentials.
    """
    preset = providers.guess_imap_settings(body.email_address)
    imap_host = body.imap_host or (preset[0] if preset else "")
    imap_port = body.imap_port if body.imap_host else (preset[1] if preset else 993)
    smtp_host = body.smtp_host or (preset[2] if preset else "")
    smtp_port = body.smtp_port if body.smtp_host else (preset[3] if preset else 465)
    smtp_starttls = body.smtp_starttls or (preset[4] if preset else False)
    for host in (imap_host, smtp_host):
        try:
            await transport.check_mail_host(host)
        except transport.MailHostNotAllowedError as error:
            raise refuse(
                422, "host_not_allowed",
                f"Den Server {host} kennt liam-e nicht. Trag ihn in Mistral Studio unter MAIL_IMAP_ALLOWED_HOSTS ein und verbinde das Konto dann noch einmal.",
            ) from error
        except BlockedAddressError as error:
            raise refuse(
                422, "host_not_allowed",
                "Der Mailserver ist nicht öffentlich erreichbar. Prüfe die Serveradresse und verbinde das Konto dann noch einmal.",
            ) from error
    # Resolve a secret reference once now to fail fast; only the reference is stored.
    password = body.password
    secret_name = ""
    if body.password_secret:
        try:
            secret_name = secrets.validate_secret_name(body.password_secret)
            password = await secrets.resolve_workspace_secret(secret_name)
        except secrets.SecretNameNotAllowedError as error:
            raise refuse(
                422, "secret_not_allowed",
                "Diesen Secret-Namen kannst du nicht für ein Mailkonto verwenden. Leg in Mistral Studio ein eigenes Secret mit einem Namen wie yahoo-app-password an und verbinde das Konto noch einmal.",
            ) from error
        except (secrets.WorkspaceSecretNotFoundError, httpx.HTTPError) as error:
            raise refuse(
                404, "secret_not_found",
                "Das Secret wurde nicht gefunden oder ist nicht lesbar. Prüfe den Namen und die Freigabe in Mistral Studio und verbinde dein Konto noch einmal.",
            ) from error
    try:
        await check_imap_login(
            email_address=body.email_address,
            password=password,
            host=imap_host,
            port=imap_port,
        )
    except (imaplib.IMAP4.error, OSError, BlockedAddressError, transport.MailHostNotAllowedError) as error:
        raise refuse(
            502, "login_failed",
            "Die Anmeldung beim Mailserver hat nicht geklappt. Prüfe deine Serveradresse und das App-Passwort und verbinde das Konto noch einmal.",
        ) from error
    try:
        account = await upsert_account(
            provider=providers.IMAP,
            auth_type="imap_password",
            email_address=body.email_address,
        )
    except AccountConflictError as error:
        raise refuse(
            409, "account_exists",
            "Diese Adresse ist schon über einen anderen Weg verbunden. Entferne das Konto zuerst, wenn du die Verbindung wechseln willst.",
        ) from error
    payload: dict[str, Any] = {
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_starttls": smtp_starttls,
    }
    if body.password_secret:
        payload["password_secret"] = secret_name
    else:
        payload["password"] = body.password
    await credential_access.store_credential(
        account_id=account.id,
        kind="imap_password",
        encrypted_payload=crypto.encrypt_payload(payload),
    )
    return AccountOut.from_model(account)


@router.get(
    "/oauth/{provider}/authorize",
    operation_id="mail_account_oauth_authorize",
    summary="Start the OAuth2 flow for google or microsoft; open the returned URL in the browser",
)
async def oauth_authorize(
    provider: Literal["google", "microsoft"], request: Request
) -> OAuthAuthorizeOut:
    """Start the OAuth2 flow for ``google`` or ``microsoft`` and return the URL to open in a browser.

    The response carries the ``authorization_url`` plus the signed ``state`` that the provider
    echoes back to the callback; nothing is redirected here. Answers 503 when that provider's
    OAuth client is not configured.
    """
    if not providers.oauth_configured(provider):
        raise HTTPException(
            status_code=503,
            detail=f"OAuth für {provider} ist nicht konfiguriert (MAIL_OAUTH_{provider.upper()}_CLIENT_ID/SECRET fehlt).",
        )
    redirect_uri = (
        f"{_redirect_base(request)}/api/v1/mail/accounts/oauth/{provider}/callback"
    )
    state = providers.sign_state({"provider": provider, "redirect_uri": redirect_uri})
    return OAuthAuthorizeOut(
        authorization_url=providers.authorization_url(
            provider, redirect_uri=redirect_uri, state=state
        ),
        state=state,
    )


@router.get(
    "/oauth/{provider}/callback",
    operation_id="mail_account_oauth_callback",
    summary="OAuth2 redirect target: exchanges the code and stores the encrypted tokens",
)
async def oauth_callback(
    provider: Literal["google", "microsoft"],
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> AccountOut:
    """OAuth2 redirect target: exchange the authorization code and store the encrypted tokens.

    The signed ``state`` must match ``provider``; the provider's e-mail address decides which
    mail account is created or updated (auth type ``oauth2``) and returned.
    An address already using another connection type answers 409 without changing credentials.
    """
    try:
        payload = providers.verify_state(state)
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail=f"Ungültiger OAuth-State: {error}"
        ) from error
    if payload.get("provider") != provider:
        raise HTTPException(
            status_code=400, detail="OAuth-State passt nicht zum Provider."
        )
    try:
        tokens = await providers.exchange_code(
            provider, code=code, redirect_uri=payload["redirect_uri"]
        )
        email_address = await providers.fetch_account_email(
            provider, access_token=tokens["access_token"]
        )
    except (httpx.HTTPStatusError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=502, detail=f"OAuth-Token-Austausch fehlgeschlagen: {error}"
        ) from error
    if not email_address:
        raise HTTPException(
            status_code=502, detail="Der Provider hat keine E-Mail-Adresse geliefert."
        )
    try:
        account = await upsert_account(
            provider=provider, auth_type="oauth2", email_address=email_address
        )
    except AccountConflictError as error:
        raise refuse(
            409, "account_exists",
            "Diese Adresse ist schon über einen anderen Weg verbunden. Entferne das Konto zuerst, wenn du die Verbindung wechseln willst.",
        ) from error
    await credential_access.store_credential(
        account_id=account.id,
        kind="oauth2_tokens",
        encrypted_payload=crypto.encrypt_payload(tokens),
    )
    return AccountOut.from_model(account)


@router.delete(
    "/{account_id}",
    operation_id="mail_account_delete",
    status_code=204,
    summary="Delete an account and all its data",
)
async def delete_account(account_id: str) -> None:
    """Delete a mail account together with its credentials, synced messages and sync state.

    ``account_id`` selects the account; the data cannot be restored. Answers 204 on success and
    404 for an unknown account.
    """
    deleted = await account_access.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden.")
    await credential_access.delete_for_account(account_id)
    await message_access.delete_for_account(account_id)
    await sync_state_access.delete_for_account(account_id)


@router.post(
    "/{account_id}/sync",
    operation_id="mail_account_sync",
    summary="Sync the account into the local mail index",
)
async def sync_account(account_id: str) -> SyncOut:
    """Sync one connected account's mail into the local index and return the result.

    ``account_id`` selects the account; the response reports the ``status``, the number of
    messages ``synced`` and the new ``cursor``. Provider failures do not raise — they return
    status ``error`` with ``error_code``.
    """
    try:
        result = await sync_service.sync_account(account_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return SyncOut(status=result.status, synced=result.synced, cursor=result.cursor, error_code=result.error_code)
