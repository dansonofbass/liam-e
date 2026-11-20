"""Sync Studio inboxes and parse full-content messages without headers.

The Gmail connector returns no Reply-To field, so ``reply_to_json`` stays empty and replies go to
the sender.

Cursors are Unix seconds: newest, optionally followed by :gap_after:gap_before
for an unfinished window. Window boundaries overlap by one second.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from db.accessors import mail_message as message_access
from db.models.mail_account import MailAccount
from db.models.mail_message import MailMessage

from api.mail import connectors
from api.mail.sync_types import Reread, SyncChanges, attachments, body_text, common


logger = logging.getLogger(__name__)


async def _thread_page(provider: str, args: dict) -> tuple[list[dict], str]:
    page = await connectors.call_read_tool_json(provider, "search_threads", args)
    threads = page.get("threads") if isinstance(page, dict) else None
    if not isinstance(threads, list) or not all(isinstance(row, dict) and isinstance(row.get("id"), str)
                                               and row["id"] for row in threads):
        raise ValueError("Incomplete connector thread listing")
    token = page.get("nextPageToken")
    if token is None:
        token = ""
    if not isinstance(token, str):
        raise ValueError("Invalid connector page token")
    return threads, token


async def _search(provider: str, query: str) -> list[dict[str, Any]]:
    threads = []
    seen = set()
    token = ""
    while True:
        args: dict[str, Any] = {"query": query, "pageSize": 50}
        if token:
            args["pageToken"] = token
        rows, token = await _thread_page(provider, args)
        threads.extend(rows)
        if not token:
            return threads
        if token in seen:
            raise ValueError("Repeated connector page token")
        seen.add(token)


def incremental_cursor(progress: str) -> str:
    """A legacy worker can always resume the numeric new-mail cursor."""
    if progress.startswith("initial:"):
        return str(json.loads(progress.removeprefix("initial:"))[0])
    return progress or "0"


async def fetch_changes(account: MailAccount, *, cursor: str, folders: list[str], limit: int, max_body_chars: int) -> SyncChanges:
    if not cursor.startswith("initial:"):
        return await _fetch_page(account, cursor=cursor, limit=limit, max_body_chars=max_body_chars)
    delta, previous_token = json.loads(cursor.removeprefix("initial:"))
    current = await _fetch_page(account, cursor=str(delta), limit=limit, max_body_chars=max_body_chars)
    try:
        history = await _history_page(account, cursor, limit, max_body_chars)
    except (ValueError, KeyError, TypeError, httpx.HTTPError) as error:
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
            raise
        # Keep this exact historical page for retry. The caller still verifies the mailbox
        # identity after this return and fences publication of the independent delta.
        logger.warning("Connector history page deferred: %s", type(error).__name__)
        current.cursor = "initial:" + json.dumps([current.cursor, previous_token])
        return current
    rows = {item["provider_uid"]: item for item in history.upserts}
    rows.update((item["provider_uid"], item) for item in current.upserts)
    current.unconfirmed_uids.update(history.unconfirmed_uids)
    current.upserts = [row for uid, row in rows.items() if uid not in current.unconfirmed_uids]
    current.deferred_threads.extend(history.deferred_threads)
    if history.cursor.startswith("initial:"):
        _, token = json.loads(history.cursor.removeprefix("initial:"))
        current.cursor = "initial:" + json.dumps([current.cursor, token])
    return current


async def _thread_messages(provider: str, thread_id: str):
    try:
        thread = await connectors.call_read_tool_json(provider, "get_thread",
            {"threadId": thread_id, "messageFormat": "FULL_CONTENT"})
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (401, 403):
            raise
        return [] if error.response.status_code == 404 else None
    except (ValueError, TypeError, httpx.TransportError):
        return None
    if not isinstance(thread, dict) or thread.get("id", thread_id) != thread_id:
        return None
    messages = thread.get("messages")
    return messages if isinstance(messages, list) else None


async def _history_page(account, cursor, limit, max_body_chars):
    try:
        return await _fetch_page(account, cursor=cursor, limit=limit, max_body_chars=max_body_chars)
    except httpx.HTTPStatusError as error:
        if error.response.status_code not in (400, 410):
            raise
        # Restart expired provider pagination independently of the new-mail watermark.
        return await _fetch_page(account, cursor="", limit=limit, max_body_chars=max_body_chars)


async def _fetch_page(account: MailAccount, *, cursor: str, limit: int, max_body_chars: int) -> SyncChanges:
    parts = cursor.split(":")
    valid = len(parts) in (1, 3) and all(part.isdigit() for part in parts)
    newest = int(parts[0]) if valid else 0
    page_token = ""
    if cursor.startswith("initial:"):
        _, page_token = json.loads(cursor.removeprefix("initial:"))
    gap = (int(parts[1]), int(parts[2])) if valid and len(parts) == 3 else None
    # Provider UIDs keep their local IDs, including legacy rows referenced by tasks and history.
    changes = SyncChanges()
    if connectors.mailbox_credential.get() is not None:
        known = await message_access.known_uids(account.id, "INBOX", verified_only=True)
    else:
        known = await message_access.known_uids(account.id, "INBOX")
    seen = set(known) if valid else set()

    async def scan(query: str, lower: int | None, upper: int | None) -> tuple[bool, int | None, int | None]:
        nonlocal page_token
        token = page_token if not valid else ""
        frontier = latest = None
        for _ in range(10):
            args: dict[str, Any] = {"query": query, "pageSize": 50 if valid else min(50, limit)}
            if token:
                args["pageToken"] = token
            threads, next_token = await _thread_page(account.provider, args)
            for thread in threads:
                if valid and len(changes.upserts) >= limit and frontier is not None:
                    return False, frontier, latest
                thread_id = thread["id"]
                messages = await _thread_messages(account.provider, thread_id)
                if messages is None:
                    changes.deferred_threads.append(thread_id)
                    continue
                thread_latest = None
                members = _member_labels(thread)
                for message in messages:
                    parsed = _indexed_message(message, thread_id, max_body_chars)
                    if parsed is None:
                        if thread_id not in changes.deferred_threads:
                            changes.deferred_threads.append(thread_id)
                        continue
                    stamp = int(parsed["internal_date"].timestamp())
                    thread_latest = stamp if thread_latest is None else max(thread_latest, stamp)
                    if (lower is not None and stamp <= lower) or (upper is not None and stamp >= upper):
                        continue
                    latest = stamp if latest is None else max(latest, stamp)
                    uid = parsed["provider_uid"]
                    belongs = _listed_inbox(uid, message.get("labelIds"), len(messages), members)
                    if belongs is None:
                        changes.deferred_threads.append(thread_id)
                        changes.unconfirmed_uids.add(uid)
                    elif belongs and uid not in seen:
                        changes.upserts.append(parsed)
                        seen.add(uid)
                    elif not belongs and uid in known:
                        changes.moved_out.append(uid)
                if thread_latest is not None:
                    frontier = min(thread_latest, upper) if upper is not None else thread_latest
            token = next_token
            if not valid:
                page_token = token
            if not token:
                return True, frontier, latest
            if not valid and len(changes.upserts) >= limit:
                return False, frontier, latest
        return False, frontier, latest

    old_newest = newest
    done, frontier, latest = await scan(f"in:inbox after:{newest - 1}" if valid else "in:inbox", newest - 1 if valid else None, None)
    if latest is not None:
        newest = max(newest, latest)
    if not valid and not done:
        # Finish the current page before saving its opaque successor. Equal timestamps do not skip rows.
        changes.cursor = "initial:" + json.dumps([newest, page_token])
        return changes
    if valid and not done and frontier is not None:
        gap = (gap[0] if gap else old_newest, frontier)
    if gap and gap[1] < gap[0]:
        gap = None
    if valid and gap and len(changes.upserts) < limit:
        done, frontier, _ = await scan(f"in:inbox after:{gap[0] - 1} before:{gap[1] + 1}", gap[0] - 1, gap[1] + 1)
        if done:
            gap = None
        elif frontier is not None:
            gap = (gap[0], frontier)
        if gap and gap[1] < gap[0]:
            gap = None
    changes.cursor = str(newest) + (f":{gap[0]}:{gap[1]}" if gap else "")
    if valid:
        threads = await _search(account.provider, "in:inbox newer_than:14d")
        present = {thread["id"] for thread in threads}
        labels_by_uid = {uid: labels for thread in threads
                         for uid, labels in (_member_labels(thread) or {}).items() if isinstance(labels, list)}
        fallback = {}
        cutoff = datetime.now(UTC) - timedelta(days=14)
        for uid, local_id in known.items():
            message = await message_access.get_message(local_id)
            if message is None:
                continue
            date = message.internal_date
            if date is not None and (date.replace(tzinfo=UTC) if date.tzinfo is None else date) < cutoff:
                continue
            if uid in labels_by_uid:
                labels = labels_by_uid[uid]
                if "INBOX" not in labels:
                    changes.moved_out.append(uid)
                else:
                    changes.read_updates[uid] = "UNREAD" not in labels
            elif message.thread_id not in present:
                changes.moved_out.append(uid)
            else:
                fallback[uid] = message.thread_id
        if fallback:
            unread = {thread["id"] for thread in await _search(account.provider, "is:unread in:inbox newer_than:14d")}
            changes.read_updates.update({uid: thread_id not in unread for uid, thread_id in fallback.items()})
    return changes


def _indexed_message(row, thread_id, max_body_chars):
    if not isinstance(row, dict) or not row.get("id"):
        return None
    try:
        parsed = parse_message(row, thread_id=thread_id, folder="INBOX", max_body_chars=max_body_chars)
    except (KeyError, TypeError, ValueError):
        return None
    return parsed if parsed["internal_date"] is not None else None


def _member_labels(thread: dict) -> dict[str, Any] | None:
    rows = thread.get("messages")
    if rows is None:
        return {}
    if not isinstance(rows, list) or not all(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] for row in rows):
        return None
    return {row["id"]: row.get("labelIds") for row in rows}


def _listed_inbox(uid, labels, thread_size, members) -> bool | None:
    if isinstance(labels, list):
        return "INBOX" in labels
    if members is None:
        return None
    if isinstance(members.get(uid), list):
        return "INBOX" in members[uid]
    if thread_size == 1 and (not members or set(members) == {uid}):
        return True
    # The search matched the thread, but a sibling may be its only inbox message.
    return None


async def _inbox_evidence(provider: str, thread_id: str, stamp: int):
    """Check the current inbox near the message date, even for mail outside the recent window."""
    token = ""
    query = f"in:inbox after:{max(0, stamp - 1)} before:{stamp + 2}"
    for _ in range(10):
        args = {"query": query, "pageSize": 50}
        if token:
            args["pageToken"] = token
        threads, token = await _thread_page(provider, args)
        for item in threads:
            if item["id"] != thread_id:
                continue
            return True, _member_labels(item)
        if not token:
            return False, {}
    return None, {}


async def _message_in_inbox(provider, thread_id, message, labels, thread_size, evidence) -> bool | None:
    if isinstance(labels, list):
        return "INBOX" in labels
    stamp = int(message["internal_date"].timestamp())
    if stamp not in evidence:
        try:
            evidence[stamp] = await _inbox_evidence(provider, thread_id, stamp)
        except httpx.HTTPStatusError as error:
            if error.response.status_code in (401, 403):
                raise
            evidence[stamp] = (None, {})
        except (ValueError, TypeError, httpx.TransportError):
            evidence[stamp] = (None, {})
    listed, members = evidence[stamp]
    if listed is not True:
        return listed
    return _listed_inbox(message["provider_uid"], labels, thread_size, members)


async def retry_threads(account: MailAccount, thread_ids: list[str], max_body_chars: int) -> SyncChanges:
    """Direct reads by thread ID need current inbox evidence before restoring messages."""
    recovered = SyncChanges()
    for thread_id in thread_ids:
        messages = await _thread_messages(account.provider, thread_id)
        pending = messages is None
        evidence = {}
        for row in messages or []:
            parsed = _indexed_message(row, thread_id, max_body_chars)
            if parsed is None:
                pending = True
                continue
            uid = parsed["provider_uid"]
            in_inbox = await _message_in_inbox(account.provider, thread_id, parsed, row.get("labelIds"), len(messages), evidence)
            if in_inbox is None:
                recovered.unconfirmed_uids.add(uid)
                pending = True
            elif in_inbox:
                recovered.upserts.append(parsed)
            else:
                recovered.moved_out.append(uid)
        if pending:
            recovered.deferred_threads.append(thread_id)
    return recovered


async def fetch_bodies(account: MailAccount, messages: list[MailMessage], *, max_body_chars: int) -> Reread:
    """Re-read messages thread by thread; see `Reread` for the result."""
    wanted: dict[str, list[str]] = {}
    for message in messages:
        wanted.setdefault(message.thread_id, []).append(message.provider_uid)
    found: Reread = {}
    for thread_id, uids in wanted.items():
        try:
            full = await connectors.call_read_tool_json(account.provider, "get_thread", {"threadId": thread_id, "messageFormat": "FULL_CONTENT"})
        except ValueError:
            # Text instead of JSON: an unknown thread, but also a tool error or rate limit. Not answered,
            # so the mail is asked again later, each time after a longer wait (sync.refresh_bodies).
            continue
        except httpx.HTTPError:
            break  # connector unreachable or refusing: the rest waits for the next run
        items = {item.get("id"): item for item in full.get("messages", []) if isinstance(item, dict)} if isinstance(full, dict) else {}
        for uid in uids:
            found[uid] = parse_message(items[uid], thread_id=thread_id, folder="INBOX", max_body_chars=max_body_chars) if uid in items else None
    return found


def parse_message(message: dict[str, Any], *, thread_id: str, folder: str, max_body_chars: int) -> dict[str, Any]:
    body = body_text([message.get('plaintextBody') or ''], [message.get('htmlBody') or ''])[:max_body_chars]
    labels = message.get('labelIds') or []
    sender = message.get('sender') or ''
    try:
        date = datetime.fromisoformat(message['date']) if message.get('date') else None
    except ValueError:
        date = None
    files = attachments(message.get('attachments') or [])
    return {**common(sender, {}), 'folder': folder, 'provider_uid': message['id'],
            'thread_id': thread_id, 'subject': message.get('subject') or '', 'sender': sender,
            'recipients_json': json.dumps(message.get('toRecipients') or []), 'cc_json': json.dumps(message.get('ccRecipients') or []),
            'snippet': ' '.join((message.get('snippet') or body).split())[:500], 'body_text': body,
            'internal_date': date, 'has_attachments': bool(message.get('attachmentIds') or files),
            'attachments_json': json.dumps(files), 'is_read': 'UNREAD' not in labels,
            'is_flagged': 'STARRED' in labels, 'labels_json': json.dumps(labels)}
