"""What may become a Studio MCP tool.

Deployed apps are not turned into MCP tools automatically; importing the served OpenAPI as a
Studio HTTP connector does that, and every operation then becomes one tool named after its
operation id. There is no per-operation exclusion in the spec, so the surface itself decides:
only reading GETs may reach an agent, and every changing operation has to be registered here on
purpose — the inventory test fails on any new one until someone names it.
"""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from mistralai_capabilities.fastapi.openapi import HTTP_METHODS

from conftest import build_app

# Every non-GET operation of the served app. Keep this set exact: adding an operation means
# deciding that it must not be reachable from a Studio agent.
MUTATING_OPERATIONS: frozenset[str] = frozenset(
    {
        "chat_conversation_update",
        "chat_proposal_cancel",
        "chat_proposal_confirm",
        "chat_stream",
        "chat_turn",
        "mail_account_connect_connector",
        "mail_account_connect_imap",
        "mail_account_delete",
        "mail_account_sync",
        "mail_account_update",
        "mail_actions_undo",
        "mail_message_action",
        "mail_sync_all",
    }
)

# GETs that change state as well: the OAuth flow belongs to the owner's browser, and the callback
# stores credentials and enqueues a sync. They are part of the OpenAPI, so they are named here
# rather than left out of the read-only list silently.
BROWSER_ONLY_GET_OPERATIONS: frozenset[str] = frozenset(
    {
        "mail_account_oauth_authorize",
        "mail_account_oauth_callback",
    }
)

AGENTS_MD = Path(__file__).resolve().parents[3] / "AGENTS.md"
READ_ONLY_LIST_MARKER = "lesenden Operationen:"


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return build_app()


def _operations(app: FastAPI) -> list[tuple[str, str]]:
    """``(method, operation id)`` for every operation in the served OpenAPI."""
    operations: list[tuple[str, str]] = []
    for path_item in app.openapi()["paths"].values():
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS:
                operations.append((method.upper(), operation["operationId"]))
    return operations


def _mutating_ids(app: FastAPI) -> set[str]:
    return {operation_id for method, operation_id in _operations(app) if method != "GET"}


def _read_only_get_ids(app: FastAPI) -> set[str]:
    return {
        operation_id
        for method, operation_id in _operations(app)
        if method == "GET" and operation_id not in BROWSER_ONLY_GET_OPERATIONS
    }


def test_mutating_operation_inventory(app: FastAPI) -> None:
    """Every operation that is not a GET is registered in MUTATING_OPERATIONS."""
    served = _mutating_ids(app)
    added = sorted(served - MUTATING_OPERATIONS)
    removed = sorted(MUTATING_OPERATIONS - served)
    assert not added and not removed, (
        f"new mutating operations: {added}; gone: {removed}. "
        "Register the operation in MUTATING_OPERATIONS in apps/api/tests/test_mcp_exposure.py "
        "and update the read-only rule in AGENTS.md (section Sicherheit)."
    )


def test_agents_md_read_only_list_matches_get_operations(app: FastAPI) -> None:
    """AGENTS.md names exactly the reading GETs as the surface that may be imported."""
    lines = [
        line for line in AGENTS_MD.read_text(encoding="utf-8").splitlines()
        if READ_ONLY_LIST_MARKER in line
    ]
    assert len(lines) == 1, (
        f"expected exactly one AGENTS.md line with '{READ_ONLY_LIST_MARKER}', found {len(lines)}"
    )
    listed = re.findall(r"`([^`]+)`", lines[0].split(READ_ONLY_LIST_MARKER, 1)[1])
    assert listed == sorted(_read_only_get_ids(app)), (
        "AGENTS.md lists the read-only operations differently from the served OpenAPI: "
        f"missing {sorted(_read_only_get_ids(app) - set(listed))}, "
        f"unexpected {sorted(set(listed) - _read_only_get_ids(app))}, "
        "or out of alphabetical order. Update the rule in AGENTS.md (section Sicherheit)."
    )
