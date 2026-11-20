"""Keep connector reads and writes on the same provider mailbox as its local index."""
import base64
import json
from contextlib import asynccontextmanager
from email.utils import parseaddr
from urllib.parse import quote

import httpx
from utils.mistral import MistralNotConfiguredError
from db.accessors import chat_settings, mail_sync_state
from db.models.mail_sync_state import CONNECTOR_CURSOR_PREFIX
from api.mail import connectors


class MailboxUnavailable(ValueError):
    """No positive mailbox proof. Return a reconnect status without provider content."""


def encode(binding: tuple[str, str, str], cursor: str) -> str:
    token = base64.urlsafe_b64encode(json.dumps(binding).encode()).decode()
    return f"{CONNECTOR_CURSOR_PREFIX}{token}|{cursor}"


def decode(cursor: str) -> tuple[tuple[str, str, str], str]:
    try:
        token, progress = cursor.removeprefix(CONNECTOR_CURSOR_PREFIX).split('|', 1)
        parts = json.loads(base64.b64decode(token, altchars=b'-_', validate=True))
        if not isinstance(parts, list) or len(parts) != 3 or not all(isinstance(p, str) and p for p in parts):
            raise ValueError()
        return (parts[0], parts[1], parts[2]), progress
    except (ValueError, UnicodeError):
        raise MailboxUnavailable() from None


async def _credential(provider: str) -> str:
    for scope in ('workspace', 'user', 'organization'):
        path = f"/v1/connectors/{quote(provider, safe='')}/{scope}/credentials"
        try:
            result = await connectors._get(path, {"auth_type": "oauth2"})
        except httpx.HTTPStatusError as error:
            if error.response.status_code in (403, 404):
                continue
            raise
        choices = [row for row in result.get('credentials', []) if row.get('name') and row.get('authentication_type') == 'oauth2']
        if choices:
            selected = [row for row in choices if row.get('is_default')] or choices
            if len(selected) == 1:
                return selected[0]['name']
            break
    raise MailboxUnavailable()


def _sent_by(message: dict, address: str) -> bool:
    return ('SENT' in (message.get('labelIds') or []) and
            parseaddr(message.get('sender') or '')[1].casefold() == address.casefold())


async def _anchor(account) -> tuple[str, str]:
    data = await connectors.call_read_tool_json(account.provider, 'search_threads', {'query': 'in:sent from:me', 'pageSize': 1})
    for thread in data.get('threads', []):
        for message in thread.get('messages', []):
            if thread.get('id') and message.get('id') and _sent_by(message, account.email_address):
                return thread['id'], message['id']
    raise MailboxUnavailable()


async def _verify(account, thread_id: str, message_id: str) -> None:
    thread = await connectors.call_read_tool_json(account.provider, 'get_thread', {'threadId': thread_id, 'messageFormat': 'MINIMAL'})
    if thread.get('id') != thread_id or not any(
        message.get('id') == message_id and _sent_by(message, account.email_address) for message in thread.get('messages', [])
    ):
        raise MailboxUnavailable()


@asynccontextmanager
async def bound_mailbox(account, *, cursor: str | None = None, bootstrap: bool = False, check_after: bool = False):
    """Only a full index rebuild may establish the named credential and provider-owned Sent anchor."""
    async def invalidate():
        await chat_settings.invalidate_connector(account.id)
        raise MailboxUnavailable()

    if not account.email_address or account.email_address.casefold().endswith('@connector.mistral'):
        await invalidate()
    if cursor is None:
        state = await mail_sync_state.get_state(account.id)
        if not state or not state.connector_verified:
            raise MailboxUnavailable()
        cursor = state.cursor
    token = None
    try:
        try:
            if cursor.startswith(CONNECTOR_CURSOR_PREFIX):
                (credential, thread_id, message_id), progress = decode(cursor)
            elif bootstrap:
                credential = await _credential(account.provider)
                thread_id = message_id = progress = ''
            else:
                raise MailboxUnavailable()
            token = connectors.mailbox_credential.set(credential)
            if not thread_id:
                thread_id, message_id = await _anchor(account)
            await _verify(account, thread_id, message_id)
        except (ValueError, TypeError, KeyError, AttributeError, httpx.HTTPError, MistralNotConfiguredError):
            await invalidate()
        yield (credential, thread_id, message_id), progress
        if check_after:
            try:
                await _verify(account, thread_id, message_id)
            except (ValueError, TypeError, KeyError, AttributeError, httpx.HTTPError, MistralNotConfiguredError):
                await invalidate()
    finally:
        if token is not None:
            connectors.mailbox_credential.reset(token)
