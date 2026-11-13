"""Detect newsletter senders and execute supported unsubscribe methods."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx
from db.accessors import mail_account, mail_message
from db.models.mail_account import MailAccount

from api.mail import actions, connectors, headers, netguard, send

logger = logging.getLogger(__name__)
UnsubscribeMethod = Literal['one_click', 'mailto', 'link', 'none']


@dataclass
class NewsletterSender:
    sender_id: str
    account_id: str
    address: str
    display_name: str
    total: int
    unread: int
    last_read_at: datetime | None
    method: UnsubscribeMethod
    link: str | None


@dataclass
class UnsubscribeOutcome:
    sender_id: str
    status: Literal['done', 'manual', 'failed']
    link: str | None = None
    archived_action_ids: list[str] = field(default_factory=list)
    error_code: str | None = None


def unsubscribe_method(list_unsubscribe: str, list_unsubscribe_post: str) -> tuple[UnsubscribeMethod, str | None]:
    uris = headers.parse_list_unsubscribe(list_unsubscribe)
    https = next((u for u in uris if u.lower().startswith('https://')), None)
    if list_unsubscribe_post.strip() == 'List-Unsubscribe=One-Click' and https:
        return 'one_click', https
    mailto = next((u for u in uris if u.lower().startswith('mailto:')), None)
    if mailto:
        return 'mailto', mailto
    http = next((u for u in uris if u.lower().startswith('http://')), None)
    if https or http:
        return 'link', https or http
    return 'none', None


async def find_newsletters(*, account_ids: list[str] | None = None) -> list[NewsletterSender]:
    rows = await mail_message.newsletter_senders(account_ids=account_ids)
    connector_ids = {a.id for a in await mail_account.list_accounts() if a.auth_type == connectors.CONNECTOR}
    result = []
    for row in rows:
        method, link = unsubscribe_method(row.list_unsubscribe, row.list_unsubscribe_post)
        if not row.list_unsubscribe:
            try:
                labels = json.loads(row.labels_json)
            except (ValueError, TypeError):
                labels = []
            if row.account_id not in connector_ids or not isinstance(labels, list) or not any(label in labels for label in ('CATEGORY_PROMOTIONS', 'CATEGORY_UPDATES')):
                continue
            method, link = 'none', None
        result.append(NewsletterSender(f'{row.account_id}|{row.sender_address}', row.account_id, row.sender_address, headers.sender_name(row.sender_display) or row.sender_address, row.total, row.unread, row.last_read_at, method, link))
    return result


async def sender_by_id(sender_id: str) -> NewsletterSender | None:
    parts = sender_id.split('|', 1)
    if len(parts) != 2 or not all(parts):
        return None
    return next((s for s in await find_newsletters(account_ids=[parts[0]]) if s.address == parts[1]), None)


async def unsubscribe(sender: NewsletterSender, account: MailAccount) -> UnsubscribeOutcome:
    outcome = UnsubscribeOutcome(sender.sender_id, 'failed')
    if sender.method == 'one_click':
        try:
            status = await netguard.safe_https_post(sender.link, data='List-Unsubscribe=One-Click')
            if 200 <= status < 300:
                outcome.status = 'done'
            else:
                outcome.error_code = 'unsubscribe_rejected'
        except netguard.BlockedAddressError:
            outcome.error_code = 'unsubscribe_blocked'
        except (httpx.HTTPError, OSError):
            outcome.error_code = 'unsubscribe_unreachable'
    elif sender.method == 'mailto':
        try:
            uri = urlsplit(sender.link or '')
            recipient = unquote(uri.path)
            if not recipient or '@' not in recipient or any(c.isspace() or c == ',' for c in recipient):
                outcome.error_code = 'unsubscribe_invalid'
                return outcome
            query = {}
            for key, value in parse_qsl(uri.query, keep_blank_values=True):
                query.setdefault(key.lower(), value)
            await send.send_message(account, to=[recipient], subject=query.get('subject') or 'unsubscribe', body=query.get('body') or 'unsubscribe')
            outcome.status = 'done'
        except Exception as error:
            logger.warning('%s', type(error).__name__)
            outcome.error_code = 'unsubscribe_send_failed'
    else:
        outcome.status = 'manual'
        outcome.link = sender.link if sender.method == 'link' else None
    if outcome.status != 'failed':
        for message_id in await mail_message.message_ids_from_sender(sender.account_id, sender.address):
            try:
                action = await actions.apply_action(message_id, 'archive')
                outcome.archived_action_ids.append(action.id)
            except Exception as error:
                logger.warning('%s', type(error).__name__)
    return outcome
