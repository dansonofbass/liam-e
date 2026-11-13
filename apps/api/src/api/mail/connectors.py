"""Access to the Mistral Studio connectors of this workspace (gmail, outlook, ...).

A connector keeps its own OAuth credentials inside Mistral, so providers that exist as Studio
connectors need no OAuth client of our own: the app calls their tools through the Connectors REST
API with its own credential (``MISTRAL_API_KEY``, or the worker's service-account token file).
Mail accounts connected this way have ``auth_type="mistral_connector"`` and store no credential row.

The SDK's ``beta.connectors.call_tool`` wrapper is deprecated, so this module speaks the REST API
directly: ``GET /v1/connectors``, ``GET /v1/connectors/{name}/tools``,
``POST /v1/connectors/{name}/tools/{tool}/call``.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx
from utils.mistral import mistral_api_url, mistral_app_token

# auth_type of accounts that live on a Mistral Studio connector.
CONNECTOR = "mistral_connector"

# Connector names whose tool sets are mail tools (search_threads / get_thread / send_email / ...).
MAIL_CONNECTOR_NAMES = ("gmail", "outlook", "google_mail")


def _headers() -> dict[str, str]:
    # Read per call, so a rotated token file is picked up (see utils.mistral.mistral_app_token).
    return {
        "Authorization": f"Bearer {mistral_app_token()}",
        "Accept": "application/json",
    }


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            f"{mistral_api_url()}{path}", headers=_headers(), params=params
        )
        response.raise_for_status()
        return response.json()


async def _post(path: str, payload: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{mistral_api_url()}{path}", headers=_headers(), json=payload
        )
        response.raise_for_status()
        return response.json()


async def list_connectors() -> list[dict[str, Any]]:
    """The workspace's connectors as ``[{name, id}]``."""
    data = await _get("/v1/connectors", {"page_size": 100})
    return [
        {"name": item.get("name", ""), "id": item.get("id", "")}
        for item in data.get("items", [])
    ]


async def list_tools(connector: str) -> list[dict[str, Any]]:
    """A connector's tools as ``[{name, description, input_schema}]``."""
    ref = quote(connector, safe="")
    data = await _get(f"/v1/connectors/{ref}/tools", {"page_size": 100})
    tools = data if isinstance(data, list) else data.get("items", [])
    return [
        {
            "name": tool.get("name", ""),
            "description": tool.get("description") or "",
            "input_schema": tool.get("inputSchema") or tool.get("input_schema") or {},
        }
        for tool in tools
    ]


READ_TOOLS = frozenset({"search_threads", "get_thread", "list_labels", "list_drafts"})
WRITE_TOOLS = frozenset({"send_email", "label_message", "unlabel_message"})


class ToolNotAllowedError(ValueError):
    """Raised before dispatch when a tool is outside the requested capability."""


async def _call_tool(connector: str, tool: str, arguments: dict[str, Any]) -> str:
    """Call one connector tool; returns the joined text content of the MCP-style result."""
    ref = quote(connector, safe="")
    data = await _post(
        f"/v1/connectors/{ref}/tools/{quote(tool, safe='')}/call",
        {"arguments": arguments},
    )
    return "\n".join(
        part.get("text", "") for part in data.get("content", []) if part.get("text")
    )


async def call_read_tool(connector: str, tool: str, arguments: dict[str, Any]) -> str:
    """Call an explicitly allowed read-only tool."""
    if tool not in READ_TOOLS:
        raise ToolNotAllowedError("Tool is not a permitted read tool")
    return await _call_tool(connector, tool, arguments)


async def call_read_tool_json(connector: str, tool: str, arguments: dict[str, Any]) -> Any:
    """Call an allowed read tool and parse its JSON text result."""
    return json.loads(await call_read_tool(connector, tool, arguments))


async def call_write_tool(connector: str, tool: str, arguments: dict[str, Any]) -> str:
    """Call an allowed mutation; reserved for send and confirmed mail actions."""
    if tool not in WRITE_TOOLS:
        raise ToolNotAllowedError("Tool is not a permitted write tool")
    return await _call_tool(connector, tool, arguments)
