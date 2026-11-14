"""Mistral Studio connectors under ``/api/v1/mail/connectors``.

Providers that exist as Studio connectors (gmail, outlook, ...) are connected through them — the
connector holds the OAuth credentials inside Mistral, so the app needs no OAuth client of its own
for them. ``POST /{name}/connect`` registers the connector as a mail account
(``auth_type="mistral_connector"``). Tool execution is not exposed as a route.
"""

import logging
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.mail import connectors as connector_service
from api.mail.connectors import CONNECTOR
from api.errors import refuse
from api.mail.service import AccountConflictError, upsert_account
from api.routers.api.v1.mail.accounts import AccountOut, current_account_out

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectorOut(BaseModel):
    name: str
    id: str


class ConnectorToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


def _http_error(error: Exception) -> HTTPException:
    response = getattr(error, "response", None)
    status = (
        getattr(response, "status_code", None)
        or getattr(error, "status_code", None)
        or 502
    )
    if status == 404:
        return refuse(404, "connector_not_found", "Den Connector gibt es in Mistral Studio nicht mehr. Leg ihn dort wieder an oder verbinde das Konto auf anderem Weg.")
    if status == 401:
        return refuse(502, "connector_auth_required", "Der Connector ist in Mistral Studio nicht angemeldet. Melde ihn dort unter Connector → Auth an und versuch es dann noch mal.")
    return refuse(502, "connector_failed", "Der Connector antwortet gerade nicht. Versuch es gleich noch mal.")


@router.get(
    "",
    operation_id="mail_connectors_list",
    summary="List the workspace's Mistral Studio connectors",
)
async def list_connectors() -> list[ConnectorOut]:
    """List the Mistral Studio connectors of this workspace as ``name``/``id`` pairs.

    These are the connectors that can be registered as a mail account.
    """
    try:
        connectors = await connector_service.list_connectors()
    except httpx.HTTPStatusError as error:
        raise _http_error(error) from error
    return [ConnectorOut(**c) for c in connectors]


@router.get(
    "/{name}/tools",
    operation_id="mail_connector_tools_list",
    summary="List a connector's tools",
)
async def list_tools(name: str) -> list[ConnectorToolOut]:
    """List the tools of one Studio connector with name, description and input schema.

    ``name`` is the connector name; an unknown connector answers 404.
    """
    try:
        tools = await connector_service.list_tools(name)
    except httpx.HTTPStatusError as error:
        raise _http_error(error) from error
    return [ConnectorToolOut(**t) for t in tools]


@router.post(
    "/{name}/connect",
    operation_id="mail_account_connect_connector",
    status_code=201,
    summary="Connect a Studio connector (e.g. gmail) as a mail account",
)
async def connect_connector(name: str) -> AccountOut:
    """Register a Studio connector such as ``gmail`` as a mail account and return it.

    The connector keeps the OAuth credentials inside Mistral, so the app stores no secret; the
    account's e-mail address is derived from a one-message ``search_threads`` call when the
    connector offers that tool and otherwise stays a placeholder. Answers 201.
    """
    try:
        tools = await connector_service.list_tools(name)
    except httpx.HTTPStatusError as error:
        raise _http_error(error) from error
    # Only sent mail identifies the connected sender; inbox recipients are not identity.
    email_address = f"{name}@connector.mistral"
    if any(tool["name"] == "search_threads" for tool in tools):
        try:
            data = await connector_service.call_read_tool_json(
                name, "search_threads", {"query": "in:sent", "pageSize": 1}
            )
            messages = [
                message
                for thread in data.get("threads", [])
                for message in thread.get("messages", [])
                if "SENT" in (message.get("labelIds") or [])
            ]
            if messages:
                def sent_at(message: dict[str, Any]) -> datetime:
                    try:
                        date = datetime.fromisoformat(message.get("date") or "")
                        return date if date.tzinfo else date.replace(tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        return datetime.min.replace(tzinfo=timezone.utc)

                latest = max(messages, key=sent_at)
                _, address = parseaddr(latest.get("sender") or "")
                if address.count("@") == 1 and all(address.split("@")) and not any(c.isspace() for c in address):
                    email_address = address.lower()
        except Exception:
            logger.debug(
                "Could not derive the account email from %s", name, exc_info=True
            )
    try:
        account = await upsert_account(
            provider=name, auth_type=CONNECTOR, email_address=email_address
        )
    except AccountConflictError as error:
        raise refuse(409, "account_exists", "Diese Adresse ist schon über einen anderen Weg verbunden. Entferne das Konto zuerst, wenn du die Verbindung wechseln willst.") from error
    return await current_account_out(account)
