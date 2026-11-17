"""Bounded HTTPS acquisition for the future ICS adapter (not registered).

Only normalization explicitly returns a secret-bearing URL, for owner confirmation;
fetch results and reprs never include it. Body and validators are private data and
excluded from repr. This layer checks the calendar envelope, not RFC 5545 semantics:
a successful fetch MUST still pass the isolated parser before becoming a snapshot.

Use the shared numeric-pinned transport directly, not AsyncClient (which logs URLs).
No retry, cookie jar, environment proxy or caller-supplied authentication is used.
The 15-second deadline includes resolution, all hops and streaming. Identity and gzip
are the only accepted encodings; zlib output is bounded before allocating it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import zlib
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import unquote_to_bytes

import httpx

from api.mail.netguard import PinnedStreamingTransport, is_public_ip, resolve_public

MAX_BYTES = 5 * 1024 * 1024
TOTAL_SECONDS = 15.0
MAX_REDIRECTS = 3
Resolver = Callable[[str], Awaitable[list[str]]]

# httpcore debug traces include response headers and protocol exception text.
# Suppress only this task's HTTP/1 connection traces, never unrelated mail calls.
_private_fetch: ContextVar[bool] = ContextVar("ics_private_fetch", default=False)


class _PrivateTraceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _private_fetch.get()


for _logger in ("httpcore.connection", "httpcore.http11"):
    logging.getLogger(_logger).addFilter(_PrivateTraceFilter())


@dataclass(frozen=True)
class FetchResult:
    code: str
    body: bytes | None = field(default=None, repr=False)
    etag: str | None = field(default=None, repr=False)
    last_modified: str | None = field(default=None, repr=False)


class FetchError(ValueError):
    """Only fixed redacted codes may cross this boundary."""


def normalize_url(value: str) -> str:
    """Return HTTPS spelling for explicit owner display, never for logging."""
    try:
        if (not value or any(ord(c) <= 32 or ord(c) == 127 for c in value)
                or "\\" in value or "#" in value
                or re.search(r"%(?![0-9a-fA-F]{2})", value)):
            raise ValueError
        decoded = unquote_to_bytes(value)
        decoded.decode("utf-8", errors="strict")
        if any(c < 32 or c == 127 for c in decoded):
            raise ValueError
        url = httpx.URL(value)
        if url.scheme == "webcal":
            url = url.copy_with(scheme="https")
        if (url.scheme != "https" or not url.host or url.port not in (None, 443)
                or url.userinfo or "@" in value.split("/", 3)[2]):
            raise ValueError
        return str(url)
    except Exception:
        raise FetchError("invalid_url") from None


def _validator(value: str | None) -> str | None:
    if value is not None and (len(value) > 1024 or any(ord(c) < 32 or ord(c) > 126 for c in value)):
        raise FetchError("invalid_validator")
    return value


def _public(address: str) -> bool:
    # ICS rejects mapped literals entirely, without changing the POST policy.
    return is_public_ip(address) and not (
        isinstance(ip := ipaddress.ip_address(address), ipaddress.IPv6Address)
        and ip.ipv4_mapped is not None
    )


async def _body(response: httpx.Response) -> bytes:
    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime not in ("text/calendar", "application/ics"):
        raise FetchError("invalid_format")
    encoding = response.headers.get("content-encoding", "identity").lower()
    if encoding not in ("identity", "gzip"):
        raise FetchError("invalid_encoding")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    result = bytearray()
    transferred = 0
    async for chunk in response.aiter_raw():
        transferred += len(chunk)
        if transferred > MAX_BYTES:
            raise FetchError("body_limit")
        if decoder:
            chunk = decoder.decompress(chunk, MAX_BYTES - len(result) + 1)
            if decoder.unconsumed_tail or decoder.unused_data:
                raise FetchError("body_limit")
        result.extend(chunk)
        if len(result) > MAX_BYTES:
            raise FetchError("body_limit")
        await asyncio.sleep(0)
    if decoder and not decoder.eof:
        raise FetchError("invalid_encoding")
    body = bytes(result)
    if not (body.startswith(b"BEGIN:VCALENDAR\r\n") or body.startswith(b"BEGIN:VCALENDAR\n")):
        raise FetchError("invalid_format")
    if not body.rstrip(b"\r\n").endswith(b"\nEND:VCALENDAR"):
        raise FetchError("invalid_format")
    return body


async def _fetch(
    url: str, *, etag: str | None = None, last_modified: str | None = None,
    resolver: Resolver = resolve_public,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    """Fetch privately; injected resolver/transport are offline test seams only.

    A fresh production transport is closed per hop. Injected transports are also
    closed per hop and must support reuse if the test follows redirects.
    Cancellation propagates, with response and transport cleanup in finally blocks.
    """
    try:
        async with asyncio.timeout(TOTAL_SECONDS):
            current = httpx.URL(normalize_url(url))
            origin = (current.scheme, current.host, current.port)
            headers = {"Accept": "text/calendar", "Accept-Encoding": "gzip, identity"}
            for name, value in (("If-None-Match", etag), ("If-Modified-Since", last_modified)):
                if _validator(value) is not None:
                    headers[name] = value
            for hop in range(MAX_REDIRECTS + 1):
                addresses = await resolver(current.host)
                if not addresses or any(not _public(ip) for ip in addresses):
                    raise FetchError("blocked_destination")
                wire = transport if transport is not None else PinnedStreamingTransport(
                    current.raw_host.decode("ascii"), addresses,
                )
                try:
                    request = httpx.Request("GET", current, headers=headers)
                    response = await wire.handle_async_request(request)
                    try:
                        status = response.status_code
                        if status in (301, 302, 303, 307, 308):
                            if hop == MAX_REDIRECTS:
                                raise FetchError("redirect_limit")
                            location = response.headers.get("location")
                            if not location or "#" in location or "\\" in location or any(ord(c) <= 32 for c in location):
                                raise FetchError("invalid_redirect")
                            target = httpx.URL(normalize_url(str(current.join(location))))
                            if (target.scheme, target.host, target.port) != origin:
                                raise FetchError("cross_origin")
                            current = target
                            continue
                        if status in (401, 403):
                            return FetchResult("auth_required")
                        if status == 404:
                            return FetchResult("not_found")
                        if status == 429:
                            return FetchResult("rate_limited")
                        if 500 <= status <= 599:
                            return FetchResult("provider_error")
                        if status not in (200, 304):
                            return FetchResult("http_error")
                        validators = dict(etag=_validator(response.headers.get("etag")),
                                          last_modified=_validator(response.headers.get("last-modified")))
                        if status == 304:
                            return FetchResult("not_modified", **validators)
                        return FetchResult("ok", body=await _body(response), **validators)
                    finally:
                        await response.aclose()
                finally:
                    await wire.aclose()
    except FetchError as exc:
        return FetchResult(str(exc))
    except TimeoutError:
        return FetchResult("timeout")
    except Exception:
        # Transport/parser exception text and chains can contain feed secrets.
        return FetchResult("fetch_error")
    return FetchResult("redirect_limit")


async def fetch(
    url: str, *, etag: str | None = None, last_modified: str | None = None,
    resolver: Resolver = resolve_public,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    """Acquire a feed without allowing protocol diagnostics to expose private data."""
    token = _private_fetch.set(True)
    try:
        return await _fetch(url, etag=etag, last_modified=last_modified,
                            resolver=resolver, transport=transport)
    finally:
        _private_fetch.reset(token)
