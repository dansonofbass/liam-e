"""Mail provider registry: OAuth2 endpoints/scopes for Google & Microsoft, IMAP/SMTP presets.

OAuth2 covers Gmail (``google``) and Outlook (``microsoft``); every other provider connects via
IMAP/SMTP with an app password (``imap``, settings guessed from the mail domain unless given).
OAuth ``state`` parameters are HMAC-signed with the credential-encryption key, so the flow needs
no server-side state store.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from env.mail import env as mail_env

GOOGLE = "google"
MICROSOFT = "microsoft"
IMAP = "imap"
OAUTH_PROVIDERS = (GOOGLE, MICROSOFT)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
GRAPH_API = "https://graph.microsoft.com/v1.0"

_OAUTH: dict[str, dict[str, str]] = {
    GOOGLE: {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.readonly "
            "https://www.googleapis.com/auth/gmail.send "
            "https://www.googleapis.com/auth/gmail.modify"
        ),
        "account_url": "https://www.googleapis.com/oauth2/v2/userinfo",
    },
    MICROSOFT: {
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": "openid email profile offline_access Mail.ReadWrite Mail.Send",
        "account_url": f"{GRAPH_API}/me",
    },
}

# mail domain -> (imap host, imap port, smtp host, smtp port, smtp starttls instead of implicit TLS)
IMAP_PRESETS: dict[str, tuple[str, int, str, int, bool]] = {
    "gmail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, False),
    "googlemail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, False),
    "icloud.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 465, False),
    "me.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 465, False),
    "mac.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 465, False),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, False),
    "ymail.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, False),
    "rocketmail.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, False),
    "outlook.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    "hotmail.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    "live.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    # Official Fastmail domains, including its regional domains; no custom-domain inference.
    # https://www.fastmail.help/hc/en-us/articles/6239365719055-What-domains-can-I-use-with-Fastmail
    # https://www.fastmail.help/hc/en-us/articles/1500000278342-Server-names-and-ports
    **dict.fromkeys(
        (
            "123mail.org", "150mail.com", "150ml.com", "16mail.com", "2-mail.com", "4email.net", "50mail.com",
            "airpost.net", "aliencamel.com", "allmail.net", "cluemail.com", "elitemail.org", "emailcorner.net",
            "emailengine.net", "emailengine.org", "emailgroups.net", "emailplus.org", "emailuser.net", "eml.cc",
            "f-m.fm", "fast-email.com", "fast-mail.org", "fastem.com", "fastemailer.com", "fastest.cc", "fastimap.com",
            "fastmail.ca", "fastmail.cn", "fastmail.com", "fastmail.com.au", "fastmail.fm", "fastmail.im", "fastmail.in",
            "fastmail.jp", "fastmail.mx", "fastmail.net", "fastmail.org", "fastmail.to", "fastmail.tw", "fastmailbox.net",
            "fastmessaging.com", "fea.st", "fmailbox.com", "fmgirl.com", "fmguy.com", "foobox.com", "foobox.net", "ftml.net",
            "hailmail.net", "imap-mail.com", "imap.cc", "imapmail.org", "immerbox.com", "immermail.com", "inoutbox.com",
            "internet-e-mail.com", "internet-mail.org", "internetemails.net", "internetmailing.net", "jetemail.net",
            "justemail.net", "letterboxes.org", "lifetimeaddress.com", "mail-central.com", "mail-page.com", "mailas.com",
            "mailbolt.com", "mailc.net", "mailcan.com", "mailforce.net", "mailhaven.com", "mailingaddress.org", "mailite.com",
            "mailmight.com", "mailnew.com", "mailsent.net", "mailservice.ms", "mailup.net", "mailworks.org", "mailzone.com",
            "ml1.net", "mm.st", "myfastmail.com", "mymacmail.com", "nospammail.net", "onepost.net", "ownmail.net", "penguinmail.com",
            "permanentmail.com", "petml.com", "pobox.com", "postinbox.com", "postpro.net", "proinbox.com", "promessage.com",
            "realemail.net", "reallyfast.biz", "reallyfast.info", "rushpost.com", "sent.as", "sent.at", "sent.com", "siemprebox.com",
            "siempremail.com", "speedpost.net", "speedymail.org", "ssl-mail.com", "swift-mail.com", "the-fastest.net",
            "the-quickest.com", "theinternetemail.com", "veribox.net", "veryfast.biz", "veryspeedy.net", "warpmail.net",
            "xsmail.com", "yepmail.net", "your-mail.com",
            "fastmail.co.uk", "fastmail.de", "fastmail.es", "fastmail.fr", "fastmail.nl", "fastmail.se", "fastmail.uk", "fmail.co.uk",
            "bestmail.us", "fastemail.us", "fastmail.us", "h-mail.us",
        ),
        ("imap.fastmail.com", 993, "smtp.fastmail.com", 465, False),
    ),
}


def guess_imap_settings(email_address: str) -> tuple[str, int, str, int, bool] | None:
    """The IMAP/SMTP preset for a mail domain, or None when the domain is unknown."""
    domain = email_address.rsplit("@", 1)[-1].lower()
    return IMAP_PRESETS.get(domain)


def oauth_configured(provider: str) -> bool:
    return bool(
        getattr(mail_env, f"mail_oauth_{provider}_client_id")
        and getattr(mail_env, f"mail_oauth_{provider}_client_secret")
    )


def _client_id(provider: str) -> str:
    value = getattr(mail_env, f"mail_oauth_{provider}_client_id")
    if not value:
        raise RuntimeError(f"MAIL_OAUTH_{provider.upper()}_CLIENT_ID is not configured")
    return value


def _client_secret(provider: str) -> str:
    value = getattr(mail_env, f"mail_oauth_{provider}_client_secret")
    if not value:
        raise RuntimeError(
            f"MAIL_OAUTH_{provider.upper()}_CLIENT_SECRET is not configured"
        )
    return value


def authorization_url(provider: str, *, redirect_uri: str, state: str) -> str:
    cfg = _OAUTH[provider]
    params = {
        "client_id": _client_id(provider),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scopes"],
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if provider == MICROSOFT:
        params["response_mode"] = "query"
    return f"{cfg['authorize_url']}?{urlencode(params)}"


def _state_key() -> bytes:
    key = mail_env.mail_token_encryption_key
    if not key:
        raise RuntimeError(
            "MAIL_TOKEN_ENCRYPTION_KEY is not set; OAuth state signing needs it"
        )
    return key.encode()


def sign_state(payload: dict[str, Any], *, ttl_seconds: int = 600) -> str:
    """HMAC-signed, expiring state parameter: ``base64url(json).hex(hmac)``."""
    body = {**payload, "exp": int(time.time()) + ttl_seconds}
    raw = (
        base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    sig = hmac.new(_state_key(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_state(state: str) -> dict[str, Any]:
    """Verify and decode a state parameter; raises ValueError when invalid or expired."""
    try:
        raw, sig = state.split(".", 1)
        expected = hmac.new(_state_key(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        body: dict[str, Any] = json.loads(
            base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        )
    except Exception as error:
        raise ValueError("invalid state") from error
    if int(body.get("exp", 0)) < time.time():
        raise ValueError("state expired")
    return body


async def _post_token(provider: str, data: dict[str, str]) -> dict[str, Any]:
    cfg = _OAUTH[provider]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            cfg["token_url"],
            data={
                "client_id": _client_id(provider),
                "client_secret": _client_secret(provider),
                **data,
            },
        )
        response.raise_for_status()
        return response.json()


async def exchange_code(
    provider: str, *, code: str, redirect_uri: str
) -> dict[str, Any]:
    """Trade an authorization code for tokens; ``expires_at`` (epoch seconds) is added."""
    tokens = await _post_token(
        provider,
        {
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    tokens["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))
    return tokens


async def refresh_access_token(provider: str, *, refresh_token: str) -> dict[str, Any]:
    """Refresh an access token, keeping the old refresh token when the provider omits it."""
    tokens = await _post_token(
        provider, {"refresh_token": refresh_token, "grant_type": "refresh_token"}
    )
    tokens.setdefault("refresh_token", refresh_token)
    tokens["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))
    return tokens


async def fetch_account_email(provider: str, *, access_token: str) -> str:
    """The account's own email address, from the provider's userinfo endpoint."""
    cfg = _OAUTH[provider]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            cfg["account_url"], headers={"Authorization": f"Bearer {access_token}"}
        )
        response.raise_for_status()
        info = response.json()
    if provider == GOOGLE:
        return info["email"]
    return info.get("mail") or info.get("userPrincipalName") or ""
