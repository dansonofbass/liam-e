"""Offline fetch security tests, including the actual pinned connection boundary."""

import asyncio
import gzip
import logging

import httpcore
import httpx
import pytest

from api.calendar import ics_fetch as fetcher

BODY = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
URL = "https://calendar.example.org/test-only?key=test-only"


async def public(host):
    return ["8.8.8.8", "2a00:1450:4001::1"]


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


def response(body=BODY, **headers):
    return httpx.Response(200, headers={"content-type": "text/calendar", **headers}, stream=Stream([body]))


@pytest.mark.parametrize("url", [
    "http://calendar.example.org/a", "https://calendar.example.org:444/a",
    "https://user@calendar.example.org/a", "https://calendar.example.org/a#",
    "https://calendar.example.org/%zz", "https://calendar.example.org/%ff",
    "https://calendar.example.org/%0a", "https://calendar.example.org/a b", "invalid",
])
def test_invalid_url_redacted(url):
    with pytest.raises(fetcher.FetchError, match="^invalid_url$"):
        fetcher.normalize_url(url)


def test_visible_webcal_normalization():
    assert fetcher.normalize_url("webcal://calendar.example.org/a") == "https://calendar.example.org/a"


@pytest.mark.anyio
async def test_conditional_and_private_result(caplog):
    calls = []
    def handle(request):
        calls.append(request)
        return response(etag='"test-only"', **{"last-modified": "test-only"})
    caplog.set_level(logging.DEBUG)
    result = await fetcher.fetch(URL, etag='"test-only"', last_modified="test-only",
                                 resolver=public, transport=httpx.MockTransport(handle))
    assert result.code == "ok" and result.body == BODY
    assert result.etag == '"test-only"' and result.last_modified == "test-only"
    assert calls[0].headers["if-none-match"] == '"test-only"'
    assert calls[0].headers["if-modified-since"] == "test-only"
    assert "cookie" not in calls[0].headers and "authorization" not in calls[0].headers
    assert "test-only" not in repr(result) + caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(("status", "code"), [(304, "not_modified"), (401, "auth_required"),
    (403, "auth_required"), (404, "not_found"), (429, "rate_limited"), (503, "provider_error")])
async def test_status(status, code):
    result = await fetcher.fetch(URL, resolver=public, transport=httpx.MockTransport(
        lambda request: httpx.Response(status)))
    assert result.code == code


@pytest.mark.anyio
@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["169.254.169.254"],
    ["8.8.8.8", "10.0.0.1"], ["::ffff:8.8.8.8"], ["64:ff9b::808:808"], []])
async def test_blocked_dns(addresses):
    async def resolve(host):
        return addresses
    def forbidden(request):
        pytest.fail("blocked DNS reached transport")
    assert (await fetcher.fetch(URL, resolver=resolve,
            transport=httpx.MockTransport(forbidden))).code == "blocked_destination"


@pytest.mark.anyio
async def test_rebinding_on_redirect():
    answers = ["8.8.8.8"]
    calls = []
    async def resolve(host):
        return answers
    def handle(request):
        calls.append(request)
        answers.append("127.0.0.1")
        return httpx.Response(302, headers={"location": "/next"})
    assert (await fetcher.fetch(URL, resolver=resolve,
            transport=httpx.MockTransport(handle))).code == "blocked_destination"
    assert len(calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(("location", "code", "count"), [
    ("/next", "redirect_limit", 4), ("https://other.example.org/a", "cross_origin", 1),
    ("http://calendar.example.org/a", "invalid_url", 1), ("/next#", "invalid_redirect", 1),
])
async def test_redirect_boundaries(location, code, count):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": location})
    assert (await fetcher.fetch(URL, resolver=public,
            transport=httpx.MockTransport(handle))).code == code
    assert len(calls) == count


@pytest.mark.anyio
@pytest.mark.parametrize(("body", "headers", "code"), [
    (b"<html>test-only</html>", {}, "invalid_format"),
    (BODY, {"content-type": "text/html"}, "invalid_format"),
    (gzip.compress(BODY), {"content-encoding": "gzip"}, "ok"),
    (gzip.compress(b"x" * (fetcher.MAX_BYTES + 1)), {"content-encoding": "gzip"}, "body_limit"),
    (b"x" * (fetcher.MAX_BYTES + 1), {}, "body_limit"),
    (gzip.compress(BODY)[:-3], {"content-encoding": "gzip"}, "invalid_encoding"),
    (BODY, {"content-encoding": "br"}, "invalid_encoding"),
])
async def test_body_limits_and_cleanup(body, headers, code):
    reply = response(body, **headers)
    assert (await fetcher.fetch(URL, resolver=public,
            transport=httpx.MockTransport(lambda request: reply))).code == code
    assert reply.is_closed and reply.stream.closed


@pytest.mark.anyio
async def test_total_deadline_closes_response(monkeypatch):
    closed = []
    class Slow(Stream):
        async def __aiter__(self):
            await asyncio.sleep(1)
            yield BODY
        async def aclose(self):
            closed.append(True)
    monkeypatch.setattr(fetcher, "TOTAL_SECONDS", 0.01)
    reply = httpx.Response(200, headers={"content-type": "text/calendar"}, stream=Slow([]))
    assert (await fetcher.fetch(URL, resolver=public,
            transport=httpx.MockTransport(lambda request: reply))).code == "timeout"
    assert closed == [True]


@pytest.mark.anyio
async def test_actual_pinning_tls_and_redacted_logs(monkeypatch, caplog):
    connections, names = [], []
    class Wire(httpcore.AsyncMockStream):
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert ssl_context.check_hostname
            names.append(server_hostname)
            return self
    async def connect(self, host, port, **kwargs):
        connections.append((host, port))
        return Wire([b"HTTP/1.1 200 OK\r\nETag: test-only\r\nContent-Type: text/calendar\r\nContent-Length: "
                     + str(len(BODY)).encode() + b"\r\n\r\n" + BODY])
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    caplog.set_level(logging.DEBUG)
    result = await fetcher.fetch(URL, resolver=public)
    assert result.code == "ok" and result.body == BODY
    assert connections == [("8.8.8.8", 443)] and names == ["calendar.example.org"]
    assert "test-only" not in caplog.text
