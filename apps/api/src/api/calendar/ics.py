"""Unregistered ICS adapter and cancellable, resource-bounded parser entry points.

Each call uses a fresh exec subprocess, not a thread/fork of the API. Linux/POSIX
RLIMIT_AS caps address space at 256 MiB, RLIMIT_CPU at 5 seconds; an 8-second wall
budget includes startup and IPC. Timeout and cancellation kill and reap the child.
Platforms without resource limits fail closed. Pipes are bounded (16 MiB input,
32 MiB output); stderr is discarded and only fixed codes cross the error boundary.
The subprocess disables network access and logging. Small trusted JSON conversion
in the parent is offloaded, not feed parsing or recurrence work.

A 304 needs previously normalized events, not a stale window or cached raw ICS.
The adapter has no source lookup, persistence, scheduling or registration side effect.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta

from api.calendar.adapters import Event, Occurrence, Snapshot
from api.calendar.ics_fetch import FetchResult, fetch

MAX_INPUT = 16 * 1024 * 1024
MAX_OUTPUT = 32 * 1024 * 1024
MAX_BODY = 5 * 1024 * 1024


class ICSError(ValueError):
    """Only fixed redacted codes; no provider exception is chained."""


@dataclass(frozen=True)
class Limits:
    wall_seconds: float = 8.0
    cpu_seconds: int = 5
    memory_bytes: int = 256 * 1024 * 1024
    components: int = 10_000
    occurrences: int = 50_000

    def validate(self):
        if any(type(value) is not int for value in (self.cpu_seconds, self.memory_bytes, self.components, self.occurrences)):
            raise ICSError("invalid_limits")
        if not (0 < self.wall_seconds <= 8 and 1 <= self.cpu_seconds <= 5
                and 16 * 1024 * 1024 <= self.memory_bytes <= 256 * 1024 * 1024
                and 1 <= self.components <= 10_000 and 1 <= self.occurrences <= 50_000):
            raise ICSError("invalid_limits")


def default_window(today: date | None = None):
    today = today or datetime.now(UTC).date()
    return (datetime.combine(today - timedelta(days=30), datetime.min.time(), UTC),
            datetime.combine(today + timedelta(days=180), datetime.min.time(), UTC))


def _encode(payload):
    encoded = json.dumps(payload, ensure_ascii=True).encode()
    if len(encoded) > MAX_INPUT:
        raise ICSError("input_limit")
    return encoded


def _decode(output):
    payload = json.loads(output)
    code = payload.get("error")
    if code:
        if code not in {"invalid_format", "unsupported_semantics", "invalid_window",
                        "component_limit", "expansion_limit", "memory_limit", "output_limit",
                        "input_limit", "isolation_unavailable"}:
            code = "parser_error"
        raise ICSError(code)
    events = [Event(**item) for item in payload["events"]]
    rows = []
    for item in payload["occurrences"]:
        for name in ("start_date", "end_date"):
            if item[name] is not None:
                item[name] = date.fromisoformat(item[name])
        for name in ("start_at", "end_at"):
            if item[name] is not None:
                item[name] = datetime.fromisoformat(item[name])
        rows.append(Occurrence(**item))
    return Snapshot(events, rows, True)


async def _run(payload, limits):
    limits.validate()
    payload["limits"] = asdict(limits)
    encoded = await asyncio.to_thread(_encode, payload)
    process = None
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable, "-m", "api.calendar.ics_worker", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    ))
    try:
        async with asyncio.timeout(limits.wall_seconds):
            process = await asyncio.shield(spawn)

            async def send():
                process.stdin.write(encoded)
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()

            async def receive():
                chunks, size = [], 0
                while chunk := await process.stdout.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_OUTPUT:
                        raise ICSError("output_limit")
                    chunks.append(chunk)
                return b"".join(chunks)

            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(send())
                received = tasks.create_task(receive())
                tasks.create_task(process.wait())
            if process.returncode != 0:
                raise ICSError("parser_resource_limit")
            return await asyncio.to_thread(_decode, received.result())
    except TimeoutError:
        raise ICSError("parser_timeout") from None
    except ICSError:
        raise
    except Exception:
        raise ICSError("parser_error") from None
    finally:
        # Shield creation so cancellation cannot abandon a child before obtaining
        # its handle. Always reap before returning, including caller cancellation.
        async def cleanup():
            child = process
            if child is None:
                try:
                    child = await spawn
                except Exception:
                    return
            if child.returncode is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            # Drain pipes after kill: wait() alone can hang on a paused stdout
            # reader when cancellation interrupts a large result transfer.
            await child.communicate()
            await child.wait()

        cleanup_task = asyncio.create_task(cleanup())
        cancelled = False
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancelled = True
        cleanup_task.result()
        if cancelled:
            raise asyncio.CancelledError


async def parse(body: bytes, start: datetime, end: datetime, *, fallback_zone: str,
                limits: Limits = Limits()) -> Snapshot:
    if len(body) > MAX_BODY:
        raise ICSError("input_limit")
    return await _run({"body": base64.b64encode(body).decode("ascii"), "fallback": fallback_zone,
                       "start": start.isoformat(), "end": end.isoformat()}, limits)


async def reexpand(events: list[Event], start: datetime, end: datetime, *,
                   limits: Limits = Limits()) -> Snapshot:
    return await _run({"events": [asdict(event) for event in events],
                       "start": start.isoformat(), "end": end.isoformat()}, limits)


@dataclass(repr=False)
class ICSAdapter:
    url: str = field(repr=False)
    fallback_zone: str
    previous_events: list[Event] | None = field(default=None, repr=False)
    etag: str | None = field(default=None, repr=False)
    last_modified: str | None = field(default=None, repr=False)
    limits: Limits = Limits()

    async def snapshot(self, source_id: str, start: datetime, end: datetime) -> Snapshot:
        result: FetchResult = await fetch(self.url, etag=self.etag, last_modified=self.last_modified)
        if result.code == "not_modified":
            if self.previous_events is None:
                raise ICSError("missing_cached_components")
            if any(event.recurrence.get("fallback") != self.fallback_zone for event in self.previous_events):
                raise ICSError("cached_zone_mismatch")
            return await reexpand(self.previous_events, start, end, limits=self.limits)
        if result.code != "ok" or result.body is None:
            raise ICSError(result.code)
        return await parse(result.body, start, end, fallback_zone=self.fallback_zone, limits=self.limits)
