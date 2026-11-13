"""Durable mail jobs and periodic account polling."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from db.accessors import mail_account, mail_job, mail_sync_state
from env.mail import env as mail_env

from api.mail import sync

_handlers: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}


def register_handler(kind: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    _handlers[kind] = handler


async def enqueue_sync(account_id: str) -> bool:
    return await mail_job.enqueue("sync", {"account_id": account_id}, dedupe_key=f"sync:{account_id}") is not None


async def enqueue_insights(account_id: str) -> bool:
    return await mail_job.enqueue("insights", {"account_id": account_id}, dedupe_key=f"insights:{account_id}") is not None


async def _sync(payload: dict[str, Any]) -> None:
    await sync.sync_account(payload["account_id"])


register_handler("sync", _sync)


async def run_once(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    job = await mail_job.claim_next(now, stale_after=timedelta(minutes=mail_env.mail_sync_stale_minutes))
    if job is None:
        return False
    try:
        await _handlers[job.kind](json.loads(job.payload_json))
    except Exception as error:
        retry_at = None if isinstance(error, LookupError) or job.attempts >= 3 else now + timedelta(seconds=30 * job.attempts)
        await mail_job.fail(job.id, type(error).__name__, retry_at=retry_at)
    else:
        await mail_job.finish(job.id)
    return True


async def enqueue_due_syncs(now: datetime, *, older_than_minutes: float | None, skip_auth_expired: bool) -> list[str]:
    queued = []
    for account in await mail_account.list_accounts():
        if not account.is_active:
            continue
        state = await mail_sync_state.get_state(account.id)
        if state and skip_auth_expired and state.last_error == "auth_expired":
            continue
        if older_than_minutes is not None and state and state.last_sync_at and state.last_sync_at >= now - timedelta(minutes=older_than_minutes):
            continue
        if await enqueue_sync(account.id):
            queued.append(account.id)
    return queued


def poll_due(now: datetime, last_poll: datetime | None, interval_minutes: int) -> bool:
    return interval_minutes > 0 and (last_poll is None or now - last_poll >= timedelta(minutes=interval_minutes))


async def worker_loop(
    stop: asyncio.Event, *, clock: Callable[[], datetime] | None = None,
    wait: Callable[[asyncio.Event, float], Awaitable[None]] | None = None,
) -> None:
    clock = clock or (lambda: datetime.now(timezone.utc))
    wait = wait or _wait_for_stop
    last_poll = None
    while not stop.is_set():
        now = clock()
        interval = mail_env.mail_sync_interval_minutes
        if poll_due(now, last_poll, interval):
            last_poll = now
            try:
                await enqueue_due_syncs(now, older_than_minutes=interval / 2, skip_auth_expired=True)
            except Exception:
                pass  # Retry on the next tick without exposing provider data.
        try:
            if await run_once():
                continue
        except Exception:
            pass  # Database failures must not terminate the worker.
        await wait(stop, max(0.01, mail_env.mail_worker_poll_seconds))


async def _wait_for_stop(stop: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=timeout)
    except TimeoutError:
        pass
