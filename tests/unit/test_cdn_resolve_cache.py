"""Tests for the imgur.gg / krakenfiles.com CDN-URL resolve cache.

Both resolvers used to run on EVERY client range request. AVPlayer opens a
track with a `bytes=0-1` probe followed by chunk fetches, so a single play cost
several extra HTTPS round-trips to imgur's API (~750ms each, measured) plus
three DNS lookups apiece. On a 164MB lossless file that was the difference
between "slow" and "never starts".

Also pins the fallback bug: the retry loop caught only httpx.HTTPError, so the
ValueError raised by the SSRF pre-flight (including for a transient DNS
failure) escaped and the temp.imgur.gg fallback never ran.

Nothing here touches the network — the shared httpx client is monkeypatched.
"""

from __future__ import annotations

import httpx
import pytest

import src.streaming as streaming


@pytest.fixture(autouse=True)
def _clear_cdn_cache():
    streaming._cdn_url_cache._data.clear()
    yield
    streaming._cdn_url_cache._data.clear()


@pytest.fixture(autouse=True)
def _skip_ssrf_check(monkeypatch):
    """The pre-flight does a real getaddrinfo; neutralise it by default."""
    monkeypatch.setattr(
        streaming, "_assert_public_https_url", lambda url, source="": None
    )


class _FakeClient:
    """Counts GETs and replays scripted responses keyed by URL."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        result = self.responses.get(url)
        if result is None:
            return httpx.Response(404, request=httpx.Request("GET", url))
        if isinstance(result, Exception):
            raise result
        return httpx.Response(200, json=result, request=httpx.Request("GET", url))


def _install(monkeypatch, client):
    monkeypatch.setattr(streaming, "_get_shared_client", lambda: client)
    return client


API = "https://imgur.gg/api/file/MTkf4M4"
TEMP_API = "https://temp.imgur.gg/api/file/MTkf4M4"
CDN = "https://i.imgur.gg/MTkf4M4-track.wav"


class TestImgurResolveCache:
    @pytest.mark.asyncio
    async def test_first_call_hits_the_api(self, monkeypatch):
        client = _install(monkeypatch, _FakeClient({API: {"cdnUrl": CDN}}))
        assert await streaming.resolve_imgur_cdn_url(API) == CDN
        assert client.calls == [API]

    @pytest.mark.asyncio
    async def test_repeat_calls_are_served_from_cache(self, monkeypatch):
        client = _install(monkeypatch, _FakeClient({API: {"cdnUrl": CDN}}))
        for _ in range(5):
            assert await streaming.resolve_imgur_cdn_url(API) == CDN
        # This is the whole point: one API call for five range requests.
        assert client.calls == [API]

    @pytest.mark.asyncio
    async def test_expired_entry_is_refetched(self, monkeypatch):
        client = _install(monkeypatch, _FakeClient({API: {"cdnUrl": CDN}}))
        await streaming.resolve_imgur_cdn_url(API)
        monkeypatch.setattr(streaming._cdn_url_cache, "ttl", -1.0)
        await streaming.resolve_imgur_cdn_url(API)
        assert client.calls == [API, API]

    @pytest.mark.asyncio
    async def test_failures_are_not_cached(self, monkeypatch):
        # A 404 on both hosts must not poison the entry — the next play retries.
        client = _install(monkeypatch, _FakeClient({}))
        with pytest.raises(ValueError):
            await streaming.resolve_imgur_cdn_url(API)
        assert streaming._cdn_url_cache.get(API) is None


class TestImgurFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_temp_host_on_404(self, monkeypatch):
        client = _install(monkeypatch, _FakeClient({TEMP_API: {"cdnUrl": CDN}}))
        assert await streaming.resolve_imgur_cdn_url(API) == CDN
        assert client.calls == [API, TEMP_API]

    @pytest.mark.asyncio
    async def test_falls_back_when_the_ssrf_check_raises(self, monkeypatch):
        """The regression this file exists for.

        `_assert_public_https_url` raises ValueError — including for a plain
        DNS failure. The loop caught only httpx.HTTPError, so that escaped and
        temp.imgur.gg was never tried. Seen in production as four 502s during
        a transient container DNS outage.
        """
        client = _install(
            monkeypatch,
            _FakeClient({API: {"cdnUrl": CDN}, TEMP_API: {"cdnUrl": CDN}}),
        )
        seen: list[str] = []

        def _check(url, source=""):
            seen.append(url)
            if len(seen) == 1:
                raise ValueError(f"{source} host does not resolve: i.imgur.gg")

        monkeypatch.setattr(streaming, "_assert_public_https_url", _check)

        assert await streaming.resolve_imgur_cdn_url(API) == CDN
        assert client.calls == [API, TEMP_API]

    @pytest.mark.asyncio
    async def test_last_error_is_raised_when_every_host_fails(self, monkeypatch):
        _install(
            monkeypatch,
            _FakeClient({API: httpx.ConnectError("boom"), TEMP_API: httpx.ConnectError("boom")}),
        )
        with pytest.raises(ValueError):
            await streaming.resolve_imgur_cdn_url(API)


class TestKrakenResolveCache:
    KRAKEN_VIEW = "https://krakenfiles.com/view/WS7wzkrklJ/file.html"
    KRAKEN_CDN = "https://cdn1.krakencloud.net/uploads/2026-01-01/abc/music.mp3"

    @pytest.mark.asyncio
    async def test_repeat_calls_are_served_from_cache(self, monkeypatch):
        calls: list[str] = []

        async def _fake_get_text_capped(client, url, headers):
            calls.append(url)
            return 200, f'<audio src="{self.KRAKEN_CDN}"></audio>'

        monkeypatch.setattr(streaming, "_get_text_capped", _fake_get_text_capped)
        monkeypatch.setattr(streaming, "_get_shared_client", lambda: object())

        for _ in range(3):
            assert await streaming.resolve_kraken_cdn_url(self.KRAKEN_VIEW) == self.KRAKEN_CDN
        assert calls == [self.KRAKEN_VIEW]
