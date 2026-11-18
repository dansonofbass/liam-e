"""Narrow connector write transport; uncertain delivery never implies a retry."""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Literal

import httpx

TOOLS = frozenset({"get_event", "list_events", "create_event", "update_event", "delete_event"})


@dataclass(frozen=True)
class ToolResult:
    kind: Literal["event", "failed", "unknown"]
    event: dict | None = field(default=None, repr=False)
    status: int | None = None
    reason: str | None = None


def classify(text: str) -> ToolResult:
    try:
        event = json.loads(text)
        if isinstance(event, dict) and isinstance(event.get("id"), str) and event["id"]:
            return ToolResult("event", event=event)
    except (ValueError, TypeError):
        pass
    match = re.match(r"^Google Calendar request failed \(HTTP (\d{3}), reason ([A-Za-z]+), not applied\)", text)
    if match and 400 <= int(match[1]) < 500:
        return ToolResult("failed", status=int(match[1]), reason=match[2])
    if re.match(r"^\d+ validation errors? for call\[", text):
        return ToolResult("failed", reason="schema")
    return ToolResult("unknown")


async def call(tool: str, arguments: dict) -> ToolResult:
    if tool not in TOOLS:
        raise ValueError("calendar_tool_not_allowed")
    from api.mail.connectors import _call_tool
    try:
        # The outer deadline also bounds a slowly streaming response.
        async with asyncio.timeout(30):
            text = await _call_tool("google_calendar", tool, arguments, timeout=30)
        return classify(text)
    except (TimeoutError, httpx.TransportError, httpx.HTTPStatusError):
        return ToolResult("unknown")
