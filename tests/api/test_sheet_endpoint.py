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
        # Both signals: the HTML and the parse age independently, and an entry
        # that is genuinely old is old in both. Ageing only `timestamp` left
        # the parse looking fresh, so the endpoint answered "hit" not "stale".
        aged = time.time() - age_seconds
        meta["timestamp"] = aged
        meta["parsed_timestamp"] = aged
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

    def test_stale_revalidation_never_writes_the_callers_name(self, api_client, artist, monkeypatch):
        """The revalidated parse is written to the cache every client shares, so
        a request body's artist_name must not reach it — the same rule the miss
        path follows."""
        names: list[str | None] = []

        async def fake_fetch(url, **kwargs):
            names.append(kwargs.get("artist_name"))
            return artist

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        _populate_cache(URL, artist, age_seconds=2 * 3600)
        r = api_client.post("/sheet", json={"url": URL, "artist_name": "pwned"})
        assert r.headers["X-Cache-Status"] == "stale"
        etag = r.headers["ETag"]
        r = api_client.post(
            "/sheet", json={"url": URL, "artist_name": "pwned"}, headers={"If-None-Match": etag}
        )
        assert r.status_code == 304
        assert names == [None, None]


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


class TestSSRFGuard:
    """/sheet fetches a caller-supplied URL, so the host allowlist is the
    boundary between "tracker reader" and "internal HTTP client". These run
    against the REAL fetch pipeline — nothing is stubbed — so a regression
    that removes the guard fails here rather than silently reaching out."""

    @pytest.fixture(autouse=True)
    def _no_feed_refresh(self, monkeypatch):
        # An unknown host normally buys one TrackerHub refresh; stub it so the
        # offline gate stays offline and the assertion is about the guard.
        from src import config, fetcher
        from src.config import register_tracker_hosts

        async def _noop():
            register_tracker_hosts([])

        monkeypatch.setattr(config, "_tracker_hosts", set())
        monkeypatch.setattr(config, "_tracker_hosts_at", 0.0)
        monkeypatch.setattr(fetcher, "_refresh_tracker_hosts", _noop)
        yield

    @pytest.mark.parametrize("url", [
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata
        "http://127.0.0.1:8000/admin",                # loopback
        "http://10.0.0.5/internal",                   # RFC1918
        "https://evil.example/sheet",                 # arbitrary public host
    ])
    def test_disallowed_hosts_are_rejected(self, api_client, url):
        r = api_client.post("/sheet", json={"url": url})
        assert r.status_code == 400
        assert "host not allowed" in r.json()["detail"]

    def test_rejection_happens_before_any_request(self, api_client, monkeypatch):
        from src import fetcher

        def _boom():
            raise AssertionError("no HTTP client may be built for a blocked host")

        monkeypatch.setattr(fetcher, "_get_sheets_client", _boom)
        r = api_client.post("/sheet", json={"url": "http://169.254.169.254/"})
        assert r.status_code == 400


class TestSerializeOnce:
    """A cold miss used to serialize the whole artist three times: to cache it,
    to hash a key-sorted copy for the ETag, and to respond. The cache write now
    leaves its bytes on the artist and the response serves them."""

    def _fake_fetch_that_caches(self, artist):
        async def fake_fetch(url, **kwargs):
            _set_cached_parsed(_normalize_url(url), artist)
            return artist
        return fake_fetch

    def test_miss_serves_the_cached_bytes_and_etag(self, api_client, artist, monkeypatch):
        monkeypatch.setattr(api, "async_fetch_and_parse", self._fake_fetch_that_caches(artist))
        calls = []
        real = api.serialize_artist
        monkeypatch.setattr(api, "serialize_artist", lambda a: calls.append(1) or real(a))

        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == 200
        assert calls == [], "the miss path serialized again instead of reusing the cache write"

        cached = (api.CACHE_DIR / f"{_cache_key(_normalize_url(URL))}.parsed.json").read_bytes()
        assert r.content == cached
        from src.fetcher import get_cached_etag
        assert r.headers["ETag"] == f'"{get_cached_etag(URL)}"'

    def test_a_later_hit_carries_the_same_etag(self, api_client, artist, monkeypatch):
        monkeypatch.setattr(api, "async_fetch_and_parse", self._fake_fetch_that_caches(artist))
        miss = api_client.post("/sheet", json={"url": URL})
        hit = api_client.post("/sheet", json={"url": URL})
        assert hit.headers["X-Cache-Status"] == "hit"
        assert hit.headers["ETag"] == miss.headers["ETag"]

    def test_a_rename_does_not_reuse_the_shared_bytes(self, api_client, artist, monkeypatch):
        monkeypatch.setattr(api, "async_fetch_and_parse", self._fake_fetch_that_caches(artist))
        r = api_client.post("/sheet", json={"url": URL, "artist_name": "Renamed"})
        assert r.json()["name"] == "Renamed"
        cached = json.loads(
            (api.CACHE_DIR / f"{_cache_key(_normalize_url(URL))}.parsed.json").read_text()
        )
        assert cached["name"] != "Renamed"

    def test_a_refused_cache_write_still_serializes(self, api_client, artist, monkeypatch):
        """No wire bytes when the write did not happen — the response must still
        carry the artist, not an empty or stale body."""
        async def fake_fetch(url, **kwargs):
            return artist  # never cached, so no _wire
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == 200
        assert r.json()["name"] == artist.name


class TestProgressStream:
    """POST /sheet with Accept: application/x-ndjson streams a cold parse as
    progress lines, an artist header and the artist itself. Everything that is
    not a cold parse stays plain JSON."""

    NDJSON = {"Accept": "application/x-ndjson, application/json"}

    @staticmethod
    def _lines(response) -> list[bytes]:
        return [line for line in response.content.split(b"\n") if line]

    def test_cold_parse_streams_progress_then_the_artist(self, api_client, artist, monkeypatch):
        async def fake_fetch(url, *, timer, **kwargs):
            timer.report("fetching", "Found 3 tabs — downloading Unreleased")
            timer.report("tabs", "Read Misc", done=1, total=2)
            _set_cached_parsed(_normalize_url(url), artist)
            return artist
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)

        r = api_client.post("/sheet", json={"url": URL}, headers=self.NDJSON)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        assert r.headers["x-accel-buffering"] == "no"

        *events, payload = self._lines(r)
        events = [json.loads(e) for e in events]
        assert events[0] == {"type": "progress", "stage": "fetching",
                             "message": "Found 3 tabs — downloading Unreleased"}
        assert events[1]["done"] == 1 and events[1]["total"] == 2
        header = events[-1]
        assert header["type"] == "artist"
        assert header["bytes"] == len(payload)

        # The payload is exactly what the JSON response and the cache carry.
        cached = (api.CACHE_DIR / f"{_cache_key(_normalize_url(URL))}.parsed.json").read_bytes()
        assert payload == cached
        from src.fetcher import get_cached_etag
        assert header["etag"] == get_cached_etag(URL)

    def test_failure_ends_the_stream_with_the_json_status_and_message(self, api_client, monkeypatch):
        async def fake_fetch(url, **kwargs):
            raise AccessDeniedError("403 from provider, internal detail")
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)

        streamed = api_client.post("/sheet", json={"url": URL}, headers=self.NDJSON)
        plain = api_client.post("/sheet", json={"url": URL})
        last = json.loads(self._lines(streamed)[-1])
        assert last == {"type": "error", "status": plain.status_code,
                        "detail": plain.json()["detail"]}
        assert "internal detail" not in streamed.text

    def test_a_cache_hit_stays_plain_json_even_when_a_stream_was_asked_for(
        self, api_client, artist, monkeypatch
    ):
        _populate_cache(URL, artist)
        r = api_client.post("/sheet", json={"url": URL}, headers=self.NDJSON)
        assert r.headers["content-type"].startswith("application/json")
        assert r.headers["X-Cache-Status"] == "hit"

    def test_a_client_that_does_not_ask_gets_plain_json(self, api_client, artist, monkeypatch):
        async def fake_fetch(url, **kwargs):
            return artist
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        r = api_client.post("/sheet", json={"url": URL})
        assert r.headers["content-type"].startswith("application/json")

    def test_gzip_is_applied_by_the_stream_itself(self, api_client, artist, monkeypatch):
        async def fake_fetch(url, **kwargs):
            return artist
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        r = api_client.post(
            "/sheet", json={"url": URL},
            headers={**self.NDJSON, "Accept-Encoding": "gzip"},
        )
        assert r.headers.get("content-encoding") == "gzip"
        # httpx decodes it; what matters is that it decodes to a valid stream.
        assert json.loads(self._lines(r)[-2])["type"] == "artist"
