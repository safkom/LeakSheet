"""Unit tests for the imgur cdnUrl SSRF guard in src.streaming.

The imgur.gg file-metadata API returns a ``cdnUrl`` that the backend fetches
server-side; a compromised/poisoned API could point it at an internal host
(cloud metadata, RFC1918) and turn the proxy into an SSRF pivot. The guard
requires https and rejects any host that resolves to a non-public address.
"""

import asyncio
import socket

import httpx
import pytest

from src import streaming
from src.streaming import (
    PublicOnlyAsyncTransport,
    _assert_public_https_url,
    assert_public_redirect_target,
)


def _fake_getaddrinfo(ip: str):
    def _inner(host, port, *args, **kwargs):
        return [(2, 1, 6, "", (ip, 0))]
    return _inner


def test_rejects_cloud_metadata_endpoint(monkeypatch):
    monkeypatch.setattr(streaming.socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(ValueError, match="non-public"):
        _assert_public_https_url("https://evil.example/x.mp3", source="test")


def test_rejects_loopback(monkeypatch):
    monkeypatch.setattr(streaming.socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
    with pytest.raises(ValueError, match="non-public"):
        _assert_public_https_url("https://evil.example/x.mp3", source="test")


def test_rejects_private_rfc1918(monkeypatch):
    monkeypatch.setattr(streaming.socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.5"))
    with pytest.raises(ValueError, match="non-public"):
        _assert_public_https_url("https://evil.example/x.mp3", source="test")


def test_rejects_non_https(monkeypatch):
    monkeypatch.setattr(streaming.socket, "getaddrinfo", _fake_getaddrinfo("1.2.3.4"))
    with pytest.raises(ValueError, match="non-https"):
        _assert_public_https_url("http://cdn.example/x.mp3", source="test")


def test_allows_public_https(monkeypatch):
    monkeypatch.setattr(streaming.socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    # Public IP, https — must not raise.
    _assert_public_https_url("https://cdn.example/x.mp3", source="test")


# ---------------------------------------------------------------------------
# Redirects: follow_redirects=True lets a public origin 30x to an internal host.
# The guarded transport checks every hop, so the hop to the internal host never
# connects; stream_audio only re-checks the final URL's scheme.
# ---------------------------------------------------------------------------

async def test_transport_rejects_a_redirect_hop_to_a_private_host(monkeypatch):
    async def fake_getaddrinfo(host, port):
        ip = "169.254.169.254" if host == "metadata.internal" else "8.8.8.8"
        return [(2, 1, 6, "", (ip, 0))]

    async def fake_send(self, request):
        assert request.url.host == "cdn.example", "the private hop must never connect"
        return httpx.Response(302, headers={"Location": "https://metadata.internal/x"})

    monkeypatch.setattr(streaming, "_getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_send)
    async with httpx.AsyncClient(transport=PublicOnlyAsyncTransport(), follow_redirects=True) as client:
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await client.get("https://cdn.example/x")


def test_stream_client_uses_the_guarded_transport():
    # stream_audio relies on this for every redirect hop.
    assert isinstance(streaming._get_shared_client()._transport, PublicOnlyAsyncTransport)


async def test_redirect_to_plain_http_is_rejected_and_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"Location": "http://cdn.example/x"})
        return httpx.Response(200, content=b"bytes")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        resp = await client.send(client.build_request("GET", "https://cdn.example/x"), stream=True)
        with pytest.raises(ValueError, match="non-https"):
            await assert_public_redirect_target(resp, source="test")
        assert resp.is_closed  # body never relayed


async def test_https_final_url_passes_without_a_dns_lookup(monkeypatch):
    def no_dns(*args, **kwargs):
        raise AssertionError("the transport already resolved and checked this host")

    monkeypatch.setattr(streaming.socket, "getaddrinfo", no_dns)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        resp = await client.send(client.build_request("GET", "https://cdn.example/x"), stream=True)
        await assert_public_redirect_target(resp, source="test")
        await resp.aclose()


async def test_gdrive_request_asks_for_identity_encoding(monkeypatch):
    # Drive bytes are relayed under the upstream's Content-Length/Content-Range.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("accept-encoding", ""))
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"ID3")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(streaming, "_get_shared_client", lambda: client)
    resp = await streaming.stream_audio("https://drive.google.com/uc?export=download&id=abc")
    await resp.aclose()
    await client.aclose()
    assert seen == ["identity"]


async def test_transport_blocks_literal_private_ip():
    # The connect-time transport guard rejects a literal private/loopback host
    # before any socket is opened (defence against DNS-rebind / direct SSRF).
    transport = PublicOnlyAsyncTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await client.get("http://127.0.0.1:9/x")


async def test_transport_wraps_dns_failure_as_connect_error(monkeypatch):
    # A DNS blip (socket.gaierror) must surface as an httpx error: raw, it slipped past
    # /sheet's `except httpx.HTTPError` and became a 500 "Internal error".
    async def dns_down(*_args, **_kwargs):
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    monkeypatch.setattr(streaming, "_DNS_RETRY_DELAY_S", 0)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns_down)
    async with httpx.AsyncClient(transport=PublicOnlyAsyncTransport()) as client:
        with pytest.raises(httpx.ConnectError, match="name resolution"):
            await client.get("https://tracker.example/x")


async def test_transport_retries_a_transient_dns_failure_once(monkeypatch):
    calls = []

    async def flaky(host, *_args, **_kwargs):
        calls.append(host)
        if len(calls) == 1:
            raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]

    monkeypatch.setattr(streaming, "_DNS_RETRY_DELAY_S", 0)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", flaky)
    async with httpx.AsyncClient(transport=PublicOnlyAsyncTransport()) as client:
        # The retry's answer is the one vetted: a private address, refused before connecting.
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await client.get("https://tracker.example/x")
    assert len(calls) == 2


async def test_transport_does_not_retry_a_missing_host(monkeypatch):
    calls = []

    async def missing(host, *_args, **_kwargs):
        calls.append(host)
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(streaming, "_DNS_RETRY_DELAY_S", 0)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", missing)
    async with httpx.AsyncClient(transport=PublicOnlyAsyncTransport()) as client:
        with pytest.raises(httpx.ConnectError, match="not known"):
            await client.get("https://tracker.example/x")
    assert len(calls) == 1
