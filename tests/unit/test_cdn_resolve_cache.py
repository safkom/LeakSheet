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

import asyncio

import httpx
import pytest

import src.streaming as streaming


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
        _install(monkeypatch, _FakeClient({}))
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


class TestSingleFlight:
    """Two *simultaneous* cold requests for the same key resolve once, not twice."""

    @pytest.mark.asyncio
    async def test_concurrent_imgur_resolves_hit_the_api_once(self, monkeypatch):
        started = asyncio.Event()
        release = asyncio.Event()

        class _SlowClient:
            def __init__(self):
                self.calls: list[str] = []

            async def get(self, url, headers=None):
                self.calls.append(url)
                started.set()
                await release.wait()
                return httpx.Response(200, json={"cdnUrl": CDN}, request=httpx.Request("GET", url))

        client = _install(monkeypatch, _SlowClient())

        first = asyncio.ensure_future(streaming.resolve_imgur_cdn_url(API))
        await started.wait()
        second = asyncio.ensure_future(streaming.resolve_imgur_cdn_url(API))
        release.set()

        assert await first == CDN
        assert await second == CDN
        assert client.calls == [API]  # not [API, API]

    @pytest.mark.asyncio
    async def test_a_failed_resolve_is_not_left_in_flight(self, monkeypatch):
        # A cold resolve that fails must not wedge later callers forever.
        _install(monkeypatch, _FakeClient({}))
        with pytest.raises(ValueError):
            await streaming.resolve_imgur_cdn_url(API)
        assert API not in streaming._inflight_resolves

    @staticmethod
    def _slow_client(monkeypatch, started, release):
        class _SlowClient:
            def __init__(self):
                self.calls: list[str] = []

            async def get(self, url, headers=None):
                self.calls.append(url)
                started.set()
                await release.wait()
                return httpx.Response(
                    200, json={"cdnUrl": CDN}, request=httpx.Request("GET", url)
                )

        return _install(monkeypatch, _SlowClient())

    @pytest.mark.asyncio
    async def test_a_cancelled_waiter_does_not_break_the_shared_resolve(
        self, monkeypatch
    ):
        # AVPlayer abandons range requests routinely. A caller that goes away
        # must not cancel the resolve the remaining callers are waiting on:
        # awaiting the shared handle unshielded used to cancel it from under
        # them, and the resolve then died with InvalidStateError.
        started, release = asyncio.Event(), asyncio.Event()
        client = self._slow_client(monkeypatch, started, release)

        first = asyncio.ensure_future(streaming.resolve_imgur_cdn_url(API))
        await started.wait()
        second = asyncio.ensure_future(streaming.resolve_imgur_cdn_url(API))
        await asyncio.sleep(0)
        second.cancel()
        release.set()

        assert await first == CDN
        assert client.calls == [API]

    @pytest.mark.asyncio
    async def test_a_cancelled_first_caller_does_not_cancel_the_others(
        self, monkeypatch
    ):
        # The mirror case: the caller that happened to start the resolve goes
        # away. Its CancelledError used to be handed to every other waiter,
        # unwinding requests that were never cancelled.
        started, release = asyncio.Event(), asyncio.Event()
        client = self._slow_client(monkeypatch, started, release)

        first = asyncio.ensure_future(streaming.resolve_imgur_cdn_url(API))
        await started.wait()
        second = asyncio.ensure_future(streaming.resolve_imgur_cdn_url(API))
        await asyncio.sleep(0)
        first.cancel()
        release.set()

        assert await second == CDN
        assert client.calls == [API]
        # And the winning value still lands in the cache for the next caller.
        assert streaming._cdn_url_cache.get(API) == CDN


class TestKrakenResolveCache:
    KRAKEN_VIEW = "https://krakenfiles.com/view/WS7wzkrklJ/file.html"
    KRAKEN_CDN = "https://hs0.krakenfiles.com/uploads/01-01-2030/abc/music.mp3"

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


class TestResolverUpstreamStatus:
    """A 4xx from the kraken page or the imgur API is the host answering about one file."""

    KRAKEN_VIEW = "https://krakenfiles.com/view/WS7wzkrklJ/file.html"

    def _serve(self, monkeypatch, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(streaming, "_get_shared_client", lambda: client)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", [401, 403, 451])
    async def test_kraken_4xx_keeps_its_code(self, monkeypatch, code):
        self._serve(monkeypatch, lambda request: httpx.Response(code))
        with pytest.raises(streaming.UpstreamStatusError) as exc:
            await streaming.resolve_kraken_cdn_url(self.KRAKEN_VIEW)
        assert exc.value.status_code == code

    @pytest.mark.asyncio
    async def test_kraken_5xx_is_not_a_status_answer(self, monkeypatch):
        self._serve(monkeypatch, lambda request: httpx.Response(502))
        with pytest.raises(ValueError) as exc:
            await streaming.resolve_kraken_cdn_url(self.KRAKEN_VIEW)
        assert not isinstance(exc.value, streaming.UpstreamStatusError)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("statuses", "expected"), [
        ((451, 451), 451),
        ((401, 403), 403),
        ((404, 451), 404),  # a relayed status beats the others: 429 > 410 > 404
        ((451, 429), 429),
    ])
    async def test_imgur_4xx_on_every_host_keeps_a_code(self, monkeypatch, statuses, expected):
        by_host = dict(zip(("imgur.gg", "temp.imgur.gg"), statuses))
        self._serve(monkeypatch, lambda request: httpx.Response(by_host[request.url.host]))
        with pytest.raises(streaming.UpstreamStatusError) as exc:
            await streaming.resolve_imgur_cdn_url(API)
        assert exc.value.status_code == expected

    @pytest.mark.asyncio
    async def test_imgur_4xx_beside_a_5xx_is_not_a_status_answer(self, monkeypatch):
        by_host = {"imgur.gg": 451, "temp.imgur.gg": 502}
        self._serve(monkeypatch, lambda request: httpx.Response(by_host[request.url.host]))
        with pytest.raises(ValueError) as exc:
            await streaming.resolve_imgur_cdn_url(API)
        assert not isinstance(exc.value, streaming.UpstreamStatusError)

    @pytest.mark.asyncio
    async def test_a_page_without_media_is_non_media(self, monkeypatch):
        self._serve(monkeypatch, lambda request: httpx.Response(200, content=b"<html>no player</html>"))
        with pytest.raises(streaming.NonMediaError):
            await streaming.resolve_kraken_cdn_url(self.KRAKEN_VIEW)
        self._serve(monkeypatch, lambda request: httpx.Response(200, json={"name": "x"}))
        with pytest.raises(streaming.NonMediaError):
            await streaming.resolve_imgur_cdn_url(API)
