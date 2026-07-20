"""Contract tests for POST /sheet.

Covers the cache-miss / hit / stale-while-revalidate / ETag-304 paths and the
fetch-error → HTTP-status mapping. The fetch itself is stubbed
(``async_fetch_and_parse``); the cache is the real file cache, isolated to a tmp
dir by the autouse ``_isolate_cache`` fixture.
"""

from __future__ import annotations

import json
import time

import pytest

import src.api as api
from src.fetcher import (
    AccessDeniedError,
    InvalidURLError,
    NetworkError,
    NoTablesError,
    _cache_key,
    _normalize_url,
    _set_cache,
    _set_cached_parsed,
)
from src.parser import parse_sheet
from tests.conftest import read_synthetic

URL = "https://docs.google.com/spreadsheets/d/SHEETABC/htmlview"


@pytest.fixture
def artist():
    return parse_sheet(read_synthetic("main_tab"), "SynthWave")


def _populate_cache(url: str, artist, *, age_seconds: float = 0.0) -> str:
    """Write a servable parsed-cache entry and return its ETag (content hash)."""
    un = _normalize_url(url)
    _set_cache(un, "<html></html>", "SynthWave Tracker")   # writes the timestamp
    _set_cached_parsed(un, artist)                          # writes parsed json + hash
    if age_seconds:
        meta_path = api.CACHE_DIR / f"{_cache_key(un)}.meta.json"
        meta = json.loads(meta_path.read_text())
        meta["timestamp"] = time.time() - age_seconds
        meta_path.write_text(json.dumps(meta))
    from src.fetcher import get_cached_etag
    return get_cached_etag(url)


class TestCacheMiss:
    def test_miss_calls_fetch_and_returns_artist(self, api_client, artist, monkeypatch):
        async def fake_fetch(url, **kwargs):
            return artist

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "miss"
        assert r.headers["ETag"].startswith('"')
        body = r.json()
        assert body["name"] == "SynthWave"
        assert body["total_songs"] == 4


class TestCacheHitAndValidation:
    def test_hit_serves_cache_without_fetching(self, api_client, artist, monkeypatch):
        async def boom(*a, **k):
            raise AssertionError("must not fetch on a fresh cache hit")

        monkeypatch.setattr(api, "async_fetch_and_parse", boom)
        _populate_cache(URL, artist)
        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "hit"
        assert r.json()["total_songs"] == 4

    def test_if_none_match_returns_304(self, api_client, artist, monkeypatch):
        async def boom(*a, **k):
            raise AssertionError("must not fetch on a validated 304")

        monkeypatch.setattr(api, "async_fetch_and_parse", boom)
        etag = _populate_cache(URL, artist)
        r = api_client.post(
            "/sheet", json={"url": URL}, headers={"If-None-Match": f'"{etag}"'}
        )
        assert r.status_code == 304
        assert r.headers["X-Cache-Status"] == "validated"

    def test_stale_serves_cache_and_schedules_revalidation(self, api_client, artist, monkeypatch):
        calls: list[str] = []

        async def fake_fetch(url, **kwargs):
            calls.append(url)
            return artist

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        # Older than DEFAULT_CACHE_TTL (1h) but within STALE_CACHE_TTL (24h).
        _populate_cache(URL, artist, age_seconds=2 * 3600)
        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "stale"
        # TestClient runs background tasks after the response — revalidation fired.
        assert calls == [URL]


class TestForceRefresh:
    def test_force_refresh_bypasses_fresh_cache(self, api_client, artist, monkeypatch):
        calls: list[str] = []

        async def fake_fetch(url, **kwargs):
            calls.append(url)
            return artist

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        _populate_cache(URL, artist)  # fresh cache present...
        r = api_client.post("/sheet", json={"url": URL, "force_refresh": True})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "miss"
        assert calls == [URL]  # ...but force_refresh fetched anyway


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("exc", "status"),
        [
            (InvalidURLError("bad"), 400),
            (AccessDeniedError("nope"), 403),
            (NetworkError("down"), 502),
            (NoTablesError("empty"), 404),
            (ValueError("garbage"), 422),
        ],
    )
    def test_fetch_errors_map_to_http_status(self, api_client, monkeypatch, exc, status):
        async def raiser(url, **kwargs):
            raise exc

        monkeypatch.setattr(api, "async_fetch_and_parse", raiser)
        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == status
