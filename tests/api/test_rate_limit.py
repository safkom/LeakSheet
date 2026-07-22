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
                headers={"Origin": "http://example.com"},
            )
            assert r.status_code == 429
            # CORS wrapped the 429 (CORS is the outermost middleware).
            assert r.headers.get("access-control-allow-origin") == "*"
            assert r.headers.get("retry-after") == "60"
        finally:
            api._rate_hits.clear()
