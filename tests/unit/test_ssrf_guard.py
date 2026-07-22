"""Unit tests for the imgur cdnUrl SSRF guard in src.streaming.

The imgur.gg file-metadata API returns a ``cdnUrl`` that the backend fetches
server-side; a compromised/poisoned API could point it at an internal host
(cloud metadata, RFC1918) and turn the proxy into an SSRF pivot. The guard
requires https and rejects any host that resolves to a non-public address.
"""

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
# Redirect re-validation: follow_redirects=True lets a guard-passing public
# origin 30x to an internal host. The final resp.url must be re-checked before
# any body is relayed. (Regression: this path was previously unguarded on the
# general stream/image-proxy paths — only the gdrive path re-validated.)
# ---------------------------------------------------------------------------

async def test_redirect_to_private_host_is_rejected_and_closed(monkeypatch):
    monkeypatch.setattr(streaming.socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            return httpx.Response(302, headers={"Location": "https://metadata.internal/x"})
        return httpx.Response(200, content=b"secret-internal-bytes")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        resp = await client.send(
            client.build_request("GET", "https://cdn.example/x"), stream=True
        )
        assert resp.url.host == "metadata.internal"  # redirect was followed
        with pytest.raises(ValueError, match="non-public"):
            await assert_public_redirect_target(resp, source="test")
        assert resp.is_closed  # body never relayed


async def test_redirect_to_public_host_passes(monkeypatch):
    monkeypatch.setattr(streaming.socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        resp = await client.send(
            client.build_request("GET", "https://cdn.example/x"), stream=True
        )
        await assert_public_redirect_target(resp, source="test")  # must not raise
        await resp.aclose()


async def test_transport_blocks_literal_private_ip():
    # The connect-time transport guard rejects a literal private/loopback host
    # before any socket is opened (defence against DNS-rebind / direct SSRF).
    transport = PublicOnlyAsyncTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await client.get("http://127.0.0.1:9/x")
