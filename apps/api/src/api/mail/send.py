"""Send a mail for a *confirmed* draft: SMTP for IMAP accounts, Gmail API for google, Graph for microsoft.

Only the drafts-confirm endpoint calls into here — the chat agent itself never sends (see
AGENTS.md: sending requires explicit confirmation in the chat).
"""

from __future__ import annotations

import asyncio
import base64
from email.message import EmailMessage
from email.utils import formatdate
from typing import Any

import httpx
from db.models.mail_account import MailAccount

from api.mail import connectors, providers, service, transport


def _send_smtp(
    account: MailAccount,
    credentials: dict[str, Any],
    *,
    to: list[str],
    subject: str,
    body: str,
) -> dict[str, Any]:
    """Blocking SMTP send; runs in a worker thread."""
    message = EmailMessage()
    message["From"] = account.email_address
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message.set_content(body)
    host = credentials["smtp_host"]
    port = int(credentials.get("smtp_port", 465))
    server = transport.open_smtp(
        host, port, starttls=bool(credentials.get("smtp_starttls"))
    )
    try:
        server.login(account.email_address, credentials["password"])
        server.send_message(message)
    finally:
        server.quit()
    return {"status": "sent", "via": "smtp"}


async def _send_gmail(
    account: MailAccount, token: str, *, to: list[str], subject: str, body: str
) -> dict[str, Any]:
    message = EmailMessage()
    message["From"] = account.email_address
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
    async with httpx.AsyncClient(timeout=30, base_url=providers.GMAIL_API) as client:
        response = await client.post(
            "/messages/send",
            json={"raw": raw},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return {"status": "sent", "via": "gmail", "id": response.json().get("id")}


async def _send_graph(
    account: MailAccount, token: str, *, to: list[str], subject: str, body: str
) -> dict[str, Any]:
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": address}} for address in to],
        }
    }
    async with httpx.AsyncClient(timeout=30, base_url=providers.GRAPH_API) as client:
        response = await client.post(
            "/me/sendMail", json=payload, headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return {"status": "sent", "via": "graph"}


async def send_message(
    account: MailAccount,
    *,
    to: list[str],
    subject: str,
    body: str,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one message from ``account``. Raises on provider errors; the caller maps them to HTTP."""
    if account.auth_type == connectors.CONNECTOR:
        # The connector holds the OAuth credentials inside Mistral; we just call its send tool.
        result = await connectors.call_tool(
            account.provider, "send_email", {"to": to, "subject": subject, "body": body}
        )
        return {
            "status": "sent",
            "via": f"connector:{account.provider}",
            "result": result[:500],
        }
    credentials = (
        credentials
        if credentials is not None
        else await service.load_credentials(account)
    )
    if account.provider == providers.IMAP:
        await transport.check_mail_host(credentials["smtp_host"])
        password = await service.imap_password(credentials)
        return await asyncio.to_thread(
            _send_smtp,
            account,
            {**credentials, "password": password},
            to=to,
            subject=subject,
            body=body,
        )
    if account.provider == providers.GOOGLE:
        token = await service.valid_access_token(account, credentials)
        return await _send_gmail(account, token, to=to, subject=subject, body=body)
    if account.provider == providers.MICROSOFT:
        token = await service.valid_access_token(account, credentials)
        return await _send_graph(account, token, to=to, subject=subject, body=body)
    raise ValueError(f"unknown provider {account.provider!r}")
