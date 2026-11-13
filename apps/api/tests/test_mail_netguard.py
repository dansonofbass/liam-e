"""Outbound URL checks, redirect boundaries and pinned network connections."""

import asyncio
import socket

import httpcore
import httpx
import pytest
import respx

from api.mail import netguard


@pytest.fixture
def dns(monkeypatch):
    records = {"news.example": ["8.8.8.8"]}

    async def getaddrinfo(self, host, port, **kwargs):
        values = records[host]
        if isinstance(values, Exception):
            raise values
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in values]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    return records


@pytest.mark.parametrize(("ip", "public"), [
    ("10.0.0.1", False), ("127.0.0.1", False), ("169.254.169.254", False),
    ("192.168.1.5", False), ("100.64.0.1", False), ("0.0.0.0", False),
    ("::1", False), ("fe80::1", False), ("fd00::1", False),
    ("::ffff:127.0.0.1", False), ("224.0.0.1", False), ("ff02::1", False),
    ("240.0.0.1", False), ("::", False), ("::ffff:100.64.0.1", False),
    ("64:ff9b::a9fe:a9fe", False), ("64:ff9b::808:808", False),
    ("64:ff9b:1::a00:1", False),
    ("2002:a9fe:a9fe::", False), ("2002:808:808::", False),
    ("2001:0:4136:e378:8000:63bf:3fff:fdd2", False),
    ("::127.0.0.1", False), ("::8.8.8.8", False),
    ("8.8.8.8", True), ("2a00:1450:4001::1", True),
    ("::ffff:8.8.8.8", True), ("invalid", False), ("fe80::1%eth0", False),
])
def test_is_public_ip(ip, public):
    assert netguard.is_public_ip(ip) is public


@pytest.mark.parametrize("ip", [
    "64:ff9b::a9fe:a9fe", "64:ff9b::808:808", "64:ff9b:1::a00:1",
    "2002:a9fe:a9fe::", "2002:808:808::",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2", "::127.0.0.1", "::8.8.8.8",
])
def test_ipv4_embedding_rejected_independently_of_stdlib_tables(ip, monkeypatch):
    # Model permissive classifications across Python versions.
    for name, value in (("is_global", True), ("is_private", False), ("is_reserved", False)):
        monkeypatch.setattr(netguard.ipaddress.IPv6Address, name, value)
    assert netguard.is_public_ip(ip) is False


@pytest.mark.anyio
async def test_safe_https_post_rejects_http_scheme():
    with pytest.raises(netguard.BlockedAddressError):
        await netguard.safe_https_post("http://news.example/u", data="x")


@pytest.mark.anyio
async def test_safe_https_post_rejects_private_resolution(dns):
    dns["news.example"] = ["10.0.0.5"]
    with respx.mock(assert_all_called=False) as router:
        route = router.post("https://news.example/u").respond(200)
        with pytest.raises(netguard.BlockedAddressError):
            await netguard.safe_https_post("https://news.example/u", data="x",
                                          transport=httpx.MockTransport(router.handler))
        assert not route.called


@pytest.mark.anyio
async def test_safe_https_post_rejects_redirect_to_private(dns):
    dns["intern.example"] = ["127.0.0.1"]
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://intern.example/x"})

    with pytest.raises(netguard.BlockedAddressError):
        await netguard.safe_https_post("https://news.example/u", data="x",
                                      transport=httpx.MockTransport(respond))
    assert len(calls) == 1


@pytest.mark.anyio
async def test_safe_https_post_stops_after_max_redirects(dns):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(netguard.BlockedAddressError):
        await netguard.safe_https_post("https://news.example/u", data="x",
                                      transport=httpx.MockTransport(respond))
    assert len(calls) == 4


@pytest.mark.anyio
async def test_safe_https_post_returns_status_only(dns):
    class Unreadable(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail("Response bodies must not be consumed")
            yield b""

    result = await netguard.safe_https_post(
        "https://news.example/u", data="x",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Unreadable())),
    )
    assert type(result) is int
    assert result == 200


@pytest.mark.anyio
@pytest.mark.parametrize("addresses", [["8.8.8.8", "10.0.0.1"], [], socket.gaierror()])
async def test_resolve_public_fails_closed(dns, addresses):
    dns["news.example"] = addresses
    with pytest.raises(netguard.BlockedAddressError):
        await netguard.resolve_public("news.example")


@pytest.mark.anyio
async def test_resolve_public_deduplicates(dns):
    dns["news.example"] = ["8.8.8.8", "8.8.8.8", "1.1.1.1"]
    assert await netguard.resolve_public("news.example") == ["8.8.8.8", "1.1.1.1"]


@pytest.mark.anyio
async def test_real_transport_pins_ip_and_preserves_tls_hostname(dns, monkeypatch):
    connections = []
    tls_names = []

    class Stream(httpcore.AsyncMockStream):
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls_names.append(server_hostname)
            assert ssl_context.check_hostname
            return self

    async def connect_tcp(self, host, port, **kwargs):
        connections.append((host, port))
        # A later DNS answer cannot change the already pinned destination.
        dns["news.example"] = ["127.0.0.1"]
        return Stream([b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"])

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect_tcp)
    assert await netguard.safe_https_post("https://news.example/u", data="x") == 200
    assert connections == [("8.8.8.8", 443)]
    assert tls_names == ["news.example"]


@pytest.mark.anyio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_relative_redirect_preserves_post(dns, status):
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, headers={"location": "next"})
        return httpx.Response(204)

    assert await netguard.safe_https_post(
        "https://news.example/u", data="x", max_redirects=1,
        transport=httpx.MockTransport(respond),
    ) == 204
    assert [str(request.url) for request in calls] == [
        "https://news.example/u", "https://news.example/next",
    ]
    assert all(request.method == "POST" and request.content == b"x" for request in calls)


@pytest.mark.anyio
async def test_same_host_redirect_resolves_again(dns):
    def respond(request):
        dns["news.example"] = ["127.0.0.1"]
        return httpx.Response(302, headers={"location": "/next"})

    with pytest.raises(netguard.BlockedAddressError):
        await netguard.safe_https_post(
            "https://news.example/u", data="x", transport=httpx.MockTransport(respond),
        )


@pytest.mark.anyio
@pytest.mark.parametrize(("host", "addresses"), [
    ("other.example", ["8.8.8.8"]),
    ("news.example", ["127.0.0.1"]),
    ("news.example", []),
])
async def test_backend_rejects_unapproved_destination(host, addresses, monkeypatch):
    async def unexpected_connect(*args, **kwargs):
        pytest.fail("An unapproved destination must not be dialed")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", unexpected_connect)
    backend = netguard._PinnedBackend("news.example", addresses)
    with pytest.raises(netguard.BlockedAddressError):
        await backend.connect_tcp(host, 443)


@pytest.mark.anyio
async def test_redirect_rejects_http(dns):
    transport = httpx.MockTransport(lambda request: httpx.Response(
        302, headers={"location": "http://news.example/x"},
    ))
    with pytest.raises(netguard.BlockedAddressError):
        await netguard.safe_https_post("https://news.example/u", data="x", transport=transport)
