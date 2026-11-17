"""Explicit inventory of the proposed mail read operations.

This inventory is not an authorization mechanism and does not mount any routes.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadOperation:
    operation_id: str
    path: str
    method: str = "GET"


OPERATIONS: tuple[ReadOperation, ...] = (
    ReadOperation("liam_mail_accounts", "/api/agent-read/v1/mail/accounts"),
    ReadOperation("liam_mail_search", "/api/agent-read/v1/mail/messages"),
    ReadOperation("liam_mail_read", "/api/agent-read/v1/mail/messages/{message_id}"),
    ReadOperation("liam_mail_summary", "/api/agent-read/v1/mail/summary"),
)
