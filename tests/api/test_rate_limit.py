"""Contract tests for the opt-in per-IP rate limiter (_RateLimitMiddleware).

Off by default (LEAKSHEET_RATE_LIMIT_PER_MIN unset/0). When enabled, a request
over the limit gets a 429 — and because CORS is registered as the outermost
middleware, that 429 still carries the CORS header so a browser sees a real 429
rather than an opaque network error.
"""

from __future__ import annotations

import time

import src.api as api


class TestRateLimit:
    def test_disabled_by_default(self, api_client, monkeypatch):
        monkeypatch.delenv("LEAKSHEET_RATE_LIMIT_PER_MIN", raising=False)
        api._rate_hits.clear()
        # Pre-fill a bucket; with the limiter disabled it must be ignored.
        api._rate_hits["testclient"] = [time.monotonic()] * 50
        r = api_client.get(
            "/trackers", headers={"Origin": "http://example.com"}
        )
        assert r.status_code != 429
        api._rate_hits.clear()

    def test_throttled_429_carries_cors_header(self, api_client, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_RATE_LIMIT_PER_MIN", "1")
        # Pre-fill so the very next request is already over the limit — no
        # request reaches the real endpoint, keeping the test offline.
        api._rate_hits.clear()
        api._rate_hits["testclient"] = [time.monotonic()]
        try:
            r = api_client.get(
                "/metadata?url=https://pillows.su/f/x",
                headers={"Origin": "https://sheets.safko.eu"},
            )
            assert r.status_code == 429
            # CORS wrapped the 429 (CORS is the outermost middleware).
            assert r.headers.get("access-control-allow-origin") == "https://sheets.safko.eu"
            assert r.headers.get("retry-after") == "60"
        finally:
            api._rate_hits.clear()


class TestImageProxyBucket:
    """/image-proxy is throttled separately, and far more generously.

    One artist screen fires 40-120 cover requests in a burst. Sharing the
    /sheet bucket meant 25% of them came back 429 and the era cards stayed
    blank (131 of 521 requests in a day's access log).
    """

    @staticmethod
    def _scope(path: str):
        return {
            "type": "http",
            "path": path,
            "client": ("10.0.0.1", 1234),
            "headers": [(b"host", b"example.com")],
        }

    def test_image_proxy_does_not_share_the_sheet_bucket(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_RATE_LIMIT_PER_MIN", "2")
        monkeypatch.delenv("LEAKSHEET_TRUSTED_PROXY_HOPS", raising=False)
        api._rate_hits.clear()
        mw = api._RateLimitMiddleware(app=None)
        try:
            # Exhaust the shared bucket via /sheet.
            assert mw._should_limit(self._scope("/sheet")) is False
            assert mw._should_limit(self._scope("/sheet")) is False
            assert mw._should_limit(self._scope("/sheet")) is True
            # Image art is untouched by that.
            assert mw._should_limit(self._scope("/image-proxy")) is False
        finally:
            api._rate_hits.clear()

    def test_image_proxy_ceiling_is_the_multiplier(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_RATE_LIMIT_PER_MIN", "2")
        monkeypatch.delenv("LEAKSHEET_TRUSTED_PROXY_HOPS", raising=False)
        api._rate_hits.clear()
        mw = api._RateLimitMiddleware(app=None)
        allowed = 2 * api._IMAGE_RATE_LIMIT_MULTIPLIER
        try:
            for _ in range(allowed):
                assert mw._should_limit(self._scope("/image-proxy")) is False
            assert mw._should_limit(self._scope("/image-proxy")) is True
        finally:
            api._rate_hits.clear()

    def test_unlisted_paths_are_never_limited(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_RATE_LIMIT_PER_MIN", "1")
        api._rate_hits.clear()
        mw = api._RateLimitMiddleware(app=None)
        try:
            for _ in range(5):
                assert mw._should_limit(self._scope("/trackers")) is False
        finally:
            api._rate_hits.clear()


class TestClientIPResolution:
    """Which address a request is bucketed under.

    In prod the app sits behind a platform router, so scope["client"] is that
    router for every request — bucketing on it would throttle all users at
    once. X-Forwarded-For is caller-controlled, so it is only trusted when the
    operator declares how many proxy hops to count from the right.
    """

    @staticmethod
    def _scope(peer: str, xff: str | None = None):
        headers = [(b"host", b"example.com")]
        if xff is not None:
            headers.append((b"x-forwarded-for", xff.encode()))
        return {"type": "http", "client": (peer, 1234), "headers": headers}

    def test_peer_used_when_no_hops_configured(self, monkeypatch):
        monkeypatch.delenv("LEAKSHEET_TRUSTED_PROXY_HOPS", raising=False)
        scope = self._scope("10.0.0.1", "1.2.3.4, 5.6.7.8")
        assert api._client_ip(scope) == "10.0.0.1"

    def test_rightmost_entry_is_taken_for_one_hop(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_TRUSTED_PROXY_HOPS", "1")
        scope = self._scope("10.0.0.1", "1.2.3.4, 5.6.7.8")
        assert api._client_ip(scope) == "5.6.7.8"

    def test_spoofed_prefix_cannot_shift_the_bucket(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_TRUSTED_PROXY_HOPS", "1")
        # A client prepending junk only pollutes entries the count skips over.
        a = api._client_ip(self._scope("10.0.0.1", "9.9.9.9, 5.6.7.8"))
        b = api._client_ip(self._scope("10.0.0.1", "8.8.8.8, 5.6.7.8"))
        assert a == b == "5.6.7.8"

    def test_short_chain_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_TRUSTED_PROXY_HOPS", "2")
        # Only one entry but two hops declared — the request did not come
        # through the expected chain, so nothing in the header is trusted.
        assert api._client_ip(self._scope("10.0.0.1", "1.2.3.4")) == "10.0.0.1"

    def test_missing_header_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_TRUSTED_PROXY_HOPS", "1")
        assert api._client_ip(self._scope("10.0.0.1")) == "10.0.0.1"

    def test_garbage_hop_count_is_ignored(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_TRUSTED_PROXY_HOPS", "not-a-number")
        assert api._client_ip(self._scope("10.0.0.1", "1.2.3.4")) == "10.0.0.1"
