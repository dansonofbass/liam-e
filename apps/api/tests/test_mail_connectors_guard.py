"""Connector capability boundaries."""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.mail import connectors
from api.routers.api.v1.mail import connectors as routes


def test_call_tool_route_is_gone():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/mail/connectors")
    assert TestClient(app).post("/api/v1/mail/connectors/gmail/tools/send_email", json={}).status_code in (404, 405)
    assert "mail_connector_call_tool" not in {op["operationId"] for path in app.openapi()["paths"].values() for op in path.values()}


@pytest.mark.anyio
async def test_read_call_refuses_write_tool():
    with pytest.raises(connectors.ToolNotAllowedError):
        await connectors.call_read_tool("gmail", "send_email", {})


@pytest.mark.anyio
async def test_write_call_refuses_unknown_tool():
    with pytest.raises(connectors.ToolNotAllowedError):
        await connectors.call_write_tool("gmail", "delete_label", {})


def test_only_send_and_actions_call_write_tools():
    root = Path(__file__).parents[1] / "src/api"
    allowed = {"mail/connectors.py", "mail/send.py", "mail/actions.py"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        if any(getattr(node, "attr", None) == "call_write_tool" or getattr(node, "id", None) == "call_write_tool" or getattr(node, "name", None) == "call_write_tool" for node in ast.walk(tree)):
            assert path.relative_to(root).as_posix() in allowed
