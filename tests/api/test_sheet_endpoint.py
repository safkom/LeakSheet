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
    ParseError,
    SourceGoneError,
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
        # Older than DEFAULT_CACHE_TTL (1h) but within SERVE_STALE_TTL (7d).
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


class TestServeStaleWindow:
    """An entry is served (and 304'd) for a week while a background refresh runs;
    past that the client waits for a cold parse."""

    DAY = 86400

    def test_two_day_old_entry_is_served_stale_and_revalidated(self, api_client, artist, monkeypatch):
        calls: list[str] = []

        async def fake_fetch(url, **kwargs):
            calls.append(url)
            return artist

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        _populate_cache(URL, artist, age_seconds=2 * self.DAY)
        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "stale"
        assert r.json()["total_songs"] == 4
        assert calls == [URL]  # background revalidation scheduled

    def test_matching_etag_at_two_days_gets_304_and_revalidates(self, api_client, artist, monkeypatch):
        calls: list[str] = []

        async def fake_fetch(url, **kwargs):
            calls.append(url)
            return artist

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        etag = _populate_cache(URL, artist, age_seconds=2 * self.DAY)
        r = api_client.post(
            "/sheet", json={"url": URL}, headers={"If-None-Match": f'"{etag}"'}
        )
        assert r.status_code == 304
        assert r.headers["X-Cache-Status"] == "validated"
        assert calls == [URL]

    @pytest.mark.parametrize("with_etag", [False, True])
    def test_eight_day_old_entry_is_a_cold_parse(self, api_client, artist, monkeypatch, with_etag):
        calls: list[str] = []

        async def fake_fetch(url, **kwargs):
            calls.append(url)
            return artist

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        etag = _populate_cache(URL, artist, age_seconds=8 * self.DAY)
        headers = {"If-None-Match": f'"{etag}"'} if with_etag else {}
        r = api_client.post("/sheet", json={"url": URL}, headers=headers)
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "miss"
        assert calls == [URL]

    def test_the_serve_window_is_a_week_and_outlives_the_collapse_guard(self):
        from src import fetcher

        assert fetcher.SERVE_STALE_TTL == 7 * self.DAY
        assert fetcher.COLLAPSE_GUARD_TTL == self.DAY


class TestRevalidationDropsGoneSources:
    """The serve window must not prolong content its source has removed (DMCA):
    a revalidation that finds the source gone or private deletes the entry.
    Anything that may be transient leaves the stale copy serving."""

    DAY = 86400

    @staticmethod
    def _failing_fetch(monkeypatch, exc):
        async def fake_fetch(url, **kwargs):
            raise exc

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)

    @pytest.mark.parametrize(
        ("exc", "status"),
        [(SourceGoneError("404"), 400), (AccessDeniedError("403"), 403)],
    )
    @pytest.mark.parametrize("with_etag", [False, True])
    def test_a_gone_source_stops_being_served(
        self, api_client, artist, monkeypatch, exc, status, with_etag
    ):
        from src.fetcher import get_cached_etag

        self._failing_fetch(monkeypatch, exc)
        etag = _populate_cache(URL, artist, age_seconds=2 * self.DAY)
        headers = {"If-None-Match": f'"{etag}"'} if with_etag else {}
        first = api_client.post("/sheet", json={"url": URL}, headers=headers)
        assert first.status_code in (200, 304)  # served stale; the check runs after it
        assert get_cached_etag(URL) is None
        assert not [p for p in api.CACHE_DIR.iterdir() if p.suffix != ".lock"]

        second = api_client.post("/sheet", json={"url": URL}, headers=headers)
        assert second.status_code == status

    def test_a_private_google_sheet_is_dropped_through_the_real_fetch(
        self, api_client, artist, monkeypatch
    ):
        """Private means a redirect to the sign-in page and a 200 without tables:
        the whole fetch pipeline runs, only the network is faked."""
        import httpx

        from src import fetcher
        from src.fetcher import get_cached_etag

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "accounts.google.com":
                return httpx.Response(200, html="<html><body>Sign in</body></html>")
            return httpx.Response(302, headers={"location": "https://accounts.google.com/ServiceLogin"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
        monkeypatch.setattr(fetcher, "_get_sheets_client", lambda: client)
        _populate_cache(URL, artist, age_seconds=2 * self.DAY)

        first = api_client.post("/sheet", json={"url": URL})
        assert first.headers["X-Cache-Status"] == "stale"
        assert get_cached_etag(URL) is None
        assert api_client.post("/sheet", json={"url": URL}).status_code == 403

    def test_a_failed_drop_does_not_escape_the_background_task(self, artist, monkeypatch):
        import asyncio

        def broken(url):
            raise PermissionError("read-only cache")

        self._failing_fetch(monkeypatch, SourceGoneError("404"))
        monkeypatch.setattr(api, "drop_cached_entry", broken)
        asyncio.run(api._background_revalidate(URL))

    @pytest.mark.parametrize(
        "exc",
        [
            NetworkError("HTTP 503"),
            NetworkError("HTTP 429"),
            TimeoutError(),
            NoTablesError("no tables"),
            ParseError("zero eras"),
            InvalidURLError("host not allowed for tracker fetching"),
            RuntimeError("bug"),
        ],
    )
    def test_a_transient_failure_keeps_serving_the_stale_copy(
        self, api_client, artist, monkeypatch, exc
    ):
        from src.fetcher import get_cached_etag

        self._failing_fetch(monkeypatch, exc)
        etag = _populate_cache(URL, artist, age_seconds=2 * self.DAY)
        first = api_client.post("/sheet", json={"url": URL})
        assert first.headers["X-Cache-Status"] == "stale"
        assert get_cached_etag(URL) == etag

        second = api_client.post("/sheet", json={"url": URL})
        assert second.status_code == 200
        assert second.headers["X-Cache-Status"] == "stale"
        assert second.json()["total_songs"] == 4


class TestEmptyTracker:
    """A parse with no tracks is never cached, so a 200 would hand the app an empty tracker
    to cache and list in Recents. It is a 404, like a sheet with no table data."""

    NDJSON = {"Accept": "application/x-ndjson, application/json"}

    @staticmethod
    def _empty():
        from src.models import Artist, Era
        return Artist(name="SynthWave", slug="synthwave", eras=[Era(name="Index", sections=[])])

    def test_an_empty_parse_is_a_404_on_both_responses(self, api_client, monkeypatch):
        async def fake_fetch(url, **kwargs):
            return self._empty()
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)

        plain = api_client.post("/sheet", json={"url": URL})
        streamed = api_client.post("/sheet", json={"url": URL}, headers=self.NDJSON)
        assert plain.status_code == 404
        assert plain.json()["detail"] == "No songs found in this tracker."
        last = json.loads([line for line in streamed.content.split(b"\n") if line][-1])
        assert last == {"type": "error", "status": 404, "detail": "No songs found in this tracker."}

    def test_an_empty_parse_with_failed_tabs_is_a_retryable_503(self, api_client, monkeypatch):
        """Failed tabs make it likely transient: a 5xx lets the app retry and fall back
        to its own copy, which a 4xx forbids."""
        async def fake_fetch(url, *, timer, **kwargs):
            timer.tab_loaded("100", False)
            return self._empty()
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)

        r = api_client.post("/sheet", json={"url": URL})
        assert r.status_code == 503
        assert r.json()["detail"] == "This tracker's tabs did not load. Please try again."

    @pytest.mark.parametrize("with_etag", [False, True])
    @pytest.mark.parametrize("age_seconds", [0, 2 * 86400])
    def test_an_empty_entry_on_disk_is_never_served(
        self, api_client, artist, monkeypatch, with_etag, age_seconds
    ):
        """An entry written before empty parses were refused must not be served or 304'd."""
        from src.fetcher import get_cached_etag, serialize_artist

        _populate_cache(URL, artist, age_seconds=age_seconds)
        key = _cache_key(_normalize_url(URL))
        body, etag = serialize_artist(self._empty())
        (api.CACHE_DIR / f"{key}.parsed.json").write_bytes(body)
        meta_path = api.CACHE_DIR / f"{key}.meta.json"
        meta = json.loads(meta_path.read_text())
        meta.update(content_hash=etag, total_versions=0, era_count=1)
        meta_path.write_text(json.dumps(meta))

        async def fake_fetch(url, **kwargs):
            return self._empty()
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)

        headers = {"If-None-Match": f'"{etag}"'} if with_etag else {}
        r = api_client.post("/sheet", json={"url": URL}, headers=headers)
        assert r.status_code == 404
        assert get_cached_etag(URL) is None


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
            (NetworkError("down"), 503),
            (NoTablesError("empty"), 404),
            (ValueError("garbage"), 422),
            (TimeoutError(), 503),
            (RuntimeError("bug"), 500),
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

    def test_the_stream_is_gzipped_and_still_decodes(self, api_client, artist, monkeypatch):
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

    def test_every_sheet_response_varies_on_accept(self, api_client, artist, monkeypatch):
        """JSON or NDJSON is chosen by Accept, so a cache must key on it."""
        async def fake_fetch(url, **kwargs):
            return artist
        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        streamed = api_client.post("/sheet", json={"url": URL, "use_cache": False}, headers=self.NDJSON)
        plain_miss = api_client.post("/sheet", json={"url": URL, "use_cache": False})
        _populate_cache(URL, artist)
        hit = api_client.post("/sheet", json={"url": URL})
        for r in (streamed, plain_miss, hit):
            assert "accept" in [v.strip().lower() for v in r.headers["vary"].split(",")]


class TestOneParsePerTracker:
    """A cold parse is shared, not repeated: the box cannot fit two Ye-sized parses
    at once, and a client retrying a stream it lost or a second device would start one."""

    def test_concurrent_callers_share_one_fetch(self, artist, monkeypatch):
        import asyncio

        calls: list[str] = []
        release = asyncio.Event()

        async def fake_fetch(url, *, timer, **kwargs):
            calls.append(url)
            timer.report("fetching", "Opening the tracker")
            await release.wait()
            return artist

        async def fake_warm(artist, url):
            return None

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        monkeypatch.setattr(api, "_warm_era_art", fake_warm)

        async def scenario():
            first_events: list[dict] = []
            second_events: list[dict] = []
            first = asyncio.create_task(api._parse_once(
                URL, cache_ttl=3600, use_cache=True, write_cache=True,
                timer=api.PhaseTimer(on_progress=first_events.append),
            ))
            await asyncio.sleep(0)
            # A joiner that gives up must not cancel the parse the first awaits.
            quitter = asyncio.create_task(api._parse_once(
                URL + "?gid=0", cache_ttl=0, use_cache=False, write_cache=False,
            ))
            second = asyncio.create_task(api._parse_once(
                URL, cache_ttl=0, use_cache=False, write_cache=True,
                timer=api.PhaseTimer(on_progress=second_events.append),
            ))
            await asyncio.sleep(0)
            quitter.cancel()
            release.set()
            (a1, _), (a2, _) = await asyncio.gather(first, second)
            return a1, a2, first_events

        a1, a2, first_events = asyncio.run(scenario())
        assert calls == [URL]
        assert a1 is a2 is artist
        assert first_events == [{"type": "progress", "stage": "fetching", "message": "Opening the tracker"}]
        assert api._parses == {}

    def test_a_finished_parse_is_not_reused(self, artist, monkeypatch):
        import asyncio

        calls: list[str] = []

        async def fake_fetch(url, **kwargs):
            calls.append(url)
            return artist

        async def fake_warm(artist, url):
            return None

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        monkeypatch.setattr(api, "_warm_era_art", fake_warm)

        async def twice():
            await api._parse_once(URL, cache_ttl=0, use_cache=False, write_cache=False)
            await asyncio.sleep(0)
            await api._parse_once(URL, cache_ttl=0, use_cache=False, write_cache=False)

        asyncio.run(twice())
        assert calls == [URL, URL]


class TestDisplayName:
    """artist_name is the iOS app's favourites key material (via the slug), so
    every path must apply it the same way: a warm hit that ignored it flipped
    the slug between two opens of the same tracker."""

    def _fake_fetch_that_caches(self, artist):
        async def fake_fetch(url, **kwargs):
            _set_cached_parsed(_normalize_url(url), artist)
            return artist
        return fake_fetch

    def test_every_path_serves_the_same_name_and_etag(self, api_client, artist, monkeypatch):
        monkeypatch.setattr(api, "async_fetch_and_parse", self._fake_fetch_that_caches(artist))
        body = {"url": URL, "artist_name": "Renamed"}
        miss = api_client.post("/sheet", json=body)
        hit = api_client.post("/sheet", json=body)
        assert hit.headers["X-Cache-Status"] == "hit"
        for r in (miss, hit):
            assert (r.json()["name"], r.json()["slug"]) == ("Renamed", "renamed")
        assert hit.headers["ETag"] == miss.headers["ETag"]
        not_modified = api_client.post("/sheet", json=body, headers={"If-None-Match": hit.headers["ETag"]})
        assert not_modified.status_code == 304

    def test_the_renamed_etag_differs_from_the_shared_one(self, api_client, artist, monkeypatch):
        monkeypatch.setattr(api, "async_fetch_and_parse", self._fake_fetch_that_caches(artist))
        plain = api_client.post("/sheet", json={"url": URL})
        renamed = api_client.post("/sheet", json={"url": URL, "artist_name": "Renamed"})
        assert plain.headers["ETag"] != renamed.headers["ETag"]
        # A client holding the plain copy must not get a 304 for the renamed one.
        r = api_client.post(
            "/sheet", json={"url": URL, "artist_name": "Renamed"},
            headers={"If-None-Match": plain.headers["ETag"]},
        )
        assert r.status_code == 200 and r.json()["name"] == "Renamed"


class TestRevalidationBackoff:
    async def test_a_failed_revalidation_is_not_retried_on_every_stale_hit(self, monkeypatch):
        calls: list[str] = []

        async def failing_fetch(url, **kwargs):
            calls.append(url)
            raise api.NetworkError("upstream down")

        monkeypatch.setattr(api, "async_fetch_and_parse", failing_fetch)
        await api._background_revalidate(URL)
        await api._background_revalidate(URL)
        assert calls == [URL]


class TestInvalidURL:
    @pytest.mark.parametrize("headers", [{}, {"If-None-Match": '"x"'}, {"Accept": "application/x-ndjson"}])
    def test_a_bad_port_is_a_400_on_every_path(self, api_client, headers):
        r = api_client.post("/sheet", json={"url": "https://example.com:99999/"}, headers=headers)
        assert r.status_code == 400


def test_the_rename_splice_matches_a_full_rewrite(artist):
    from src.fetcher import serialize_artist

    raw, etag = serialize_artist(artist)
    for name in ("Renamed", 'Kanye "Ye" West', "Beyoncé", artist.name):
        body, tagged = api._with_display_name(raw, etag, name)
        data = json.loads(body)
        expected = {**json.loads(raw), "name": name, "slug": api.slugify(name)}
        assert data == expected
        assert tagged == api._display_etag(etag, name)


class TestPartialLoadReachesTheTimingLine:
    """The parse runs on a timer shared by every caller; the request logging sheet_timing
    holds another, so the tab counts must be carried over or production always logs 0/0."""

    @pytest.mark.parametrize("headers,marker", [
        ({}, "status=miss "),
        ({"Accept": "application/x-ndjson"}, "status=miss stream"),
    ])
    def test_sheet_timing_carries_the_failed_tab_count(
        self, api_client, workbook_client, patch_sheets_client, caplog, headers, marker
    ):
        workbook = {
            "100": read_synthetic("main_tab"),
            "200": read_synthetic("misc_tab"),
            "300": read_synthetic("art_tab"),
        }
        names = {"100": "Unreleased", "200": "Misc", "300": "Art"}
        patch_sheets_client(workbook_client(workbook, tab_names=names, fail_gids={"300"}))

        with caplog.at_level("INFO", logger="src.api"):
            r = api_client.post("/sheet", json={"url": URL}, headers=headers)
        assert r.status_code == 200

        lines = [m for m in (rec.getMessage() for rec in caplog.records)
                 if m.startswith("sheet_timing") and marker in m]
        assert len(lines) == 1, caplog.text
        assert "failed_tabs=1/3" in lines[0]
