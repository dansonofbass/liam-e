"""Mistral Studio connectors under ``/api/v1/mail/connectors``.

Providers that exist as Studio connectors (gmail, outlook, ...) are connected through them — the
connector holds the OAuth credentials inside Mistral, so the app needs no OAuth client of its own
for them. ``POST /{name}/connect`` registers the connector as a mail account
(``auth_type="mistral_connector"``); ``POST /{name}/tools/{tool}`` calls any connector tool.
"""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.mail import connectors as connector_service
from api.mail.connectors import CONNECTOR
from api.mail.service import upsert_account
from api.routers.api.v1.mail.accounts import AccountOut

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectorOut(BaseModel):
    name: str
    id: str


class ConnectorToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


class ToolCallResult(BaseModel):
    content: str


def _http_error(error: Exception) -> HTTPException:
    response = getattr(error, "response", None)
    status = (
        getattr(response, "status_code", None)
        or getattr(error, "status_code", None)
        or 502
    )
    detail = str(error)
    if status == 404:
        return HTTPException(
            status_code=404, detail=f"Connector nicht gefunden: {detail}"
        )
    if status == 401:
        return HTTPException(
            status_code=502,
            detail="Der Connector hat keine Credentials für diese App — bitte in Mistral Studio authentifizieren (Connector → Auth).",
        )
    return HTTPException(status_code=502, detail=f"Connector-Fehler: {detail}")


@router.get(
    "",
    operation_id="mail_connectors_list",
    summary="List the workspace's Mistral Studio connectors",
)
async def list_connectors() -> list[ConnectorOut]:
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
    try:
        tools = await connector_service.list_tools(name)
    except httpx.HTTPStatusError as error:
        raise _http_error(error) from error
    # The account's email is cosmetic: derive it from a one-message search when possible.
    email_address = f"{name}@connector.mistral"
    if any(tool["name"] == "search_threads" for tool in tools):
        try:
            data = await connector_service.call_tool_json(
                name, "search_threads", {"pageSize": 1}
            )
            for thread in data.get("threads", []):
                for message in thread.get("messages", []):
                    recipients = message.get("toRecipients") or []
                    if recipients:
                        email_address = recipients[0]
                        break
        except Exception:
            logger.debug(
                "Could not derive the account email from %s", name, exc_info=True
            )
    account = await upsert_account(
        provider=name, auth_type=CONNECTOR, email_address=email_address
    )
    return AccountOut.from_model(account)


@router.post(
    "/{name}/tools/{tool}",
    operation_id="mail_connector_call_tool",
    summary="Call any tool of a Studio connector (e.g. gmail search_threads)",
)
async def call_tool(name: str, tool: str, body: ToolCallRequest) -> ToolCallResult:
    try:
        content = await connector_service.call_tool(name, tool, body.arguments)
    except httpx.HTTPStatusError as error:
        raise _http_error(error) from error
    return ToolCallResult(content=content)
