"""Optimistic index updates and provider-backed, single-use undo."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from db.accessors import mail_account as account_access
from db.accessors import mail_action as action_access
from db.accessors import mail_message as message_access
from db.models.mail_action import MailAction
from db.models.mail_message import MailMessage
from sqlalchemy.exc import IntegrityError

from api.errors import refuse

ActionKind = Literal["archive", "trash", "spam", "mark_read", "mark_unread", "restore"]
logger = logging.getLogger(__name__)


class ActionFailedError(RuntimeError):
    """The provider could not complete an action."""


class ActionUnsupportedError(RuntimeError):
    """The action is not supported for this message or provider."""


@dataclass
class UndoResult:
    restored: list[str] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


async def write_connector_labels(account, message_id: str, *, added: list[str], removed: list[str]) -> None:
    """Keep connector writes inside the guarded action boundary."""
    from api.mail import connectors

    for tool, labels in (("label_message", added), ("unlabel_message", removed)):
        if labels:
            await connectors.call_write_tool(account, tool, {"messageId": message_id, "labelIds": labels})


async def _write_provider_state(message: MailMessage, updates: dict, *, folder: str) -> None:
    """Merge a concurrent sync copy once; provider success must never be rolled back."""
    try:
        try:
            await message_access.set_state(message.id, **updates)
        except IntegrityError:
            if "provider_uid" not in updates or not await message_access.delete_duplicate(
                message.account_id, folder, updates["provider_uid"],
                keep_id=message.id, rfc_message_id=message.rfc_message_id,
            ):
                raise
            await message_access.set_state(message.id, **updates)
    except Exception as error:
        logger.warning("%s", type(error).__name__)
        raise


async def apply_action(message_id: str, kind: ActionKind) -> MailAction:
    from api.mail import action_backends

    message = await message_access.get_message(message_id)
    if message is None:
        raise refuse(404, "message_not_found", "Die Mail ist nicht mehr da.")
    sources = {"archive": ("INBOX",), "trash": ("INBOX", "ARCHIVE"), "spam": ("INBOX", "ARCHIVE"), "restore": ("ARCHIVE", "TRASH")}
    if kind in sources and message.folder not in sources[kind]:
        raise ActionUnsupportedError()
    account = await account_access.get_account(message.account_id)
    if account is None:
        raise ActionUnsupportedError()
    backend = action_backends.backend_for(account)
    previous = {key: getattr(message, key) for key in ("folder", "is_read", "provider_uid", "labels_json")}
    changes = {"folder": {"archive": "ARCHIVE", "trash": "TRASH", "spam": "SPAM", "restore": "INBOX"}[kind]} if kind in sources else {"is_read": kind == "mark_read"}
    optimistic_written = False
    try:
        await message_access.set_state(message_id, **changes)
        optimistic_written = True
        updates = await backend.apply(message, kind)
    except Exception as error:
        if optimistic_written:
            await message_access.set_state(message_id, **previous)
        logger.warning("%s", type(error).__name__)
        if isinstance(error, ActionUnsupportedError):
            raise ActionUnsupportedError() from None
        raise ActionFailedError() from None
    await _write_provider_state(message, updates, folder=changes.get("folder", message.folder))
    try:
        return await action_access.record(message_id=message.id, account_id=message.account_id, kind=kind, previous_json=json.dumps(previous))
    except Exception as error:
        logger.warning("%s", type(error).__name__)
        raise


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def undo_actions(action_ids: list[str], *, now: datetime) -> UndoResult:
    from api.mail import action_backends

    result = UndoResult()
    rows = await action_access.get_many(action_ids)
    known = {row.id for row in rows}
    result.skipped.extend(key for key in dict.fromkeys(action_ids) if key not in known)
    for action in sorted(rows, key=lambda row: (_aware(row.created_at), row.id), reverse=True):
        message = await message_access.get_message(action.message_id)
        if action.undone_at is not None or message is None:
            result.skipped.append(action.id)
            continue
        if _aware(action.created_at) < _aware(now) - timedelta(hours=24):
            result.expired.append(action.id)
            continue
        latest = await action_access.latest_open(action.message_id)
        if latest is None or latest.id != action.id:
            result.skipped.append(action.id)
            continue
        if not await action_access.mark_undone(action.id, now):
            result.skipped.append(action.id)
            continue
        try:
            account = await account_access.get_account(action.account_id)
            if account is None:
                raise ActionUnsupportedError()
            previous = json.loads(action.previous_json)
            updates = await action_backends.backend_for(account).revert(message, previous)
        except Exception as error:
            logger.warning("%s", type(error).__name__)
            await action_access.release(action.id)
            result.failed.append(action.id)
        else:
            await _write_provider_state(message, previous | updates, folder=previous["folder"])
            result.restored.append(action.id)
    return result
