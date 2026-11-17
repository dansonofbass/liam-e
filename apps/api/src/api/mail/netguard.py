"""Guard outbound HTTPS posts against non-public destinations and DNS rebinding.

Every redirect gets a fresh DNS check; all answers must be public. The production
transport pins the connection to a checked numeric address, leaving the original
HTTP origin intact for Host, TLS SNI and certificate verification. Environment
proxies are never used. Response bodies are closed without being consumed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpcore
import httpx


# Reject IPv4-embedding transition ranges regardless of Python's address tables.
_BLOCKED_IPV6_NETWORKS = tuple(ipaddress.IPv6Network(cidr) for cidr in (
    "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32", "::/96",
))


class BlockedAddressError(ValueError):
    """The destination cannot safely be used for an outbound request."""


def is_public_ip(address: str) -> bool:
    """Accept only globally routable unicast addresses, including mapped IPv4."""
    if "%" in address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if any(ip in network for network in _BLOCKED_IPV6_NETWORKS):
            return False
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


async def resolve_public(host: str) -> list[str]:
    """Resolve a host, rejecting failed, empty or partially non-public answers."""
    try:
        answers = await asyncio.get_running_loop().getaddrinfo(
            host, None, type=socket.SOCK_STREAM,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise BlockedAddressError("Destination resolution failed") from exc
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(not is_public_ip(ip) for ip in addresses):
        raise BlockedAddressError("Destination is not public")
    return addresses


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Dial only a previously checked numeric IP, never the origin's DNS name."""

    def __init__(self, host: str, addresses: list[str]):
        self._host = host
        self._addresses = tuple(addresses)
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self, host: str, port: int, timeout: float | None = None,
        local_address: str | None = None,
        socket_options: list[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host != self._host or not self._addresses or any(
            not is_public_ip(ip) for ip in self._addresses
        ):
            raise BlockedAddressError("Connection destination is not approved")
        # Numeric literals bypass DNS; httpcore still negotiates TLS on the origin name.
        return await self._backend.connect_tcp(
            self._addresses[0], port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )


class _CoreStream(httpx.AsyncByteStream):
    def __init__(self, response: httpcore.Response):
        self._response = response

    async def __aiter__(self):
        async for chunk in self._response.aiter_stream():
            yield chunk

    async def aclose(self) -> None:
        await self._response.aclose()


class PinnedStreamingTransport(httpx.AsyncBaseTransport):
    """Streaming sibling of the POST transport; callers must close responses.

    No client logging, cookies, proxies, redirects or retries are installed here.
    Each instance binds one checked origin to numeric addresses.
    """

    def __init__(self, host: str, addresses: list[str]):
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=_PinnedBackend(host, addresses),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._pool.handle_async_request(httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme, host=request.url.raw_host,
                port=request.url.port, target=request.url.raw_path,
            ),
            headers=request.headers.raw, content=request.stream,
            extensions=request.extensions,
        ))
        return httpx.Response(response.status, headers=response.headers,
                              stream=_CoreStream(response))

    async def aclose(self) -> None:
        await self._pool.aclose()


class _PinnedTransport(httpx.AsyncBaseTransport):
    """Minimal status/header-only adapter; no response content crosses this boundary."""

    def __init__(self, host: str, addresses: list[str]):
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=_PinnedBackend(host, addresses),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._pool.handle_async_request(httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme, host=request.url.raw_host,
                port=request.url.port, target=request.url.raw_path,
            ),
            headers=request.headers.raw, content=request.stream,
            extensions=request.extensions,
        ))
        try:
            return httpx.Response(response.status, headers=response.headers)
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        await self._pool.aclose()


async def safe_https_post(
    url: str, *, data: str, timeout: float = 10.0, max_redirects: int = 3,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """POST over HTTPS with checked, pinned hops; return only the final status.

    Redirects retain the POST and payload, including 301/302/303. ``transport`` is
    a test seam only: it bypasses the pinned backend but not destination checks.
    """
    if max_redirects < 0:
        raise BlockedAddressError("Invalid redirect limit")
    try:
        current = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise BlockedAddressError("Invalid destination URL") from exc
    for hop in range(max_redirects + 1):
        if current.scheme != "https" or not current.host or current.userinfo:
            raise BlockedAddressError("Only HTTPS destinations without credentials are allowed")
        addresses = await resolve_public(current.host)
        # Validate again even when tests substitute the resolver or transport.
        if not addresses or any(not is_public_ip(ip) for ip in addresses):
            raise BlockedAddressError("Destination is not public")
        async with httpx.AsyncClient(
            transport=transport if transport is not None else _PinnedTransport(
                current.raw_host.decode("ascii"), addresses,
            ),
            trust_env=False, follow_redirects=False, timeout=timeout,
        ) as client:
            async with client.stream(
                "POST", current, content=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                status = response.status_code
                location = response.headers.get("location")
        if status not in (301, 302, 303, 307, 308) or location is None:
            return status
        if hop == max_redirects:
            raise BlockedAddressError("Too many redirects")
        try:
            current = current.join(location)
        except httpx.InvalidURL as exc:
            raise BlockedAddressError("Invalid redirect URL") from exc
    raise BlockedAddressError("Too many redirects")  # Defensive: the loop always returns or raises.
