"""Unit tests for the imgur cdnUrl SSRF guard in src.streaming.

The imgur.gg file-metadata API returns a ``cdnUrl`` that the backend fetches
server-side; a compromised/poisoned API could point it at an internal host
(cloud metadata, RFC1918) and turn the proxy into an SSRF pivot. The guard
requires https and rejects any host that resolves to a non-public address.
"""

import pytest

from src import streaming
from src.streaming import _assert_public_https_url


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
