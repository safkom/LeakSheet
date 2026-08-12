"""Cache metadata invariants.

`{key}.html` and `{key}.parsed.json` share one `{key}.meta.json`, but they are
written at different times by different code paths. Conflating their freshness
served a stale parse as a fresh hit; conflating their temp files made eviction
break an in-flight write. Both are pinned here.
"""

from __future__ import annotations

import json
import time

import pytest

import src.fetcher as fetcher
from src.fetcher import _cache_key, _read_meta, _set_cache, _set_cached_parsed
from src.models import Artist


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "CACHE_DIR", tmp_path)
    yield tmp_path


def _artist(name: str = "SynthWave") -> Artist:
    return Artist(name=name, slug=name.lower(), eras=[])


URL = "https://docs.google.com/spreadsheets/d/ABC/htmlview"


class TestFreshnessSeparation:
    def test_html_write_does_not_refresh_the_parsed_cache(self):
        """The bug: a refresh that fetches HTML and then FAILS to parse made
        the previous parse read as zero seconds old, so it was served as a
        fresh hit for a whole TTL."""
        _set_cache(URL, "<html>old</html>", "T")
        _set_cached_parsed(URL, _artist())

        # Age the parse by two hours, leaving the HTML timestamp alone.
        key = _cache_key(URL)
        meta_path = fetcher.CACHE_DIR / f"{key}.meta.json"
        meta = json.loads(meta_path.read_text())
        meta["parsed_timestamp"] = time.time() - 2 * 3600
        meta_path.write_text(json.dumps(meta))

        # A new HTML fetch lands (the parse after it will throw).
        _set_cache(URL, "<html>new</html>", "T")

        assert fetcher.get_cached_age(URL) > 3600, "parse must still read as stale"
        assert fetcher._get_cached_parsed(URL, cache_ttl=3600) is None

    def test_html_write_preserves_the_content_hash(self):
        _set_cache(URL, "<html></html>", "T")
        _set_cached_parsed(URL, _artist())
        etag = fetcher.get_cached_etag(URL)
        assert etag

        _set_cache(URL, "<html>refetched</html>", "T")
        # Rebuilding the meta dict dropped this, so the next conditional
        # request could never 304.
        assert fetcher.get_cached_etag(URL) == etag

    def test_parsed_write_preserves_the_url_the_prewarm_scan_needs(self):
        _set_cache(URL, "<html></html>", "T")
        _set_cached_parsed(URL, _artist())
        assert _read_meta(_cache_key(URL))["url"] == URL

    def test_entries_written_before_the_split_still_resolve(self):
        """Existing on-disk caches carry only `timestamp`."""
        _set_cache(URL, "<html></html>", "T")
        _set_cached_parsed(URL, _artist())
        key = _cache_key(URL)
        meta_path = fetcher.CACHE_DIR / f"{key}.meta.json"
        meta = json.loads(meta_path.read_text())
        aged = time.time() - 600
        meta.pop("parsed_timestamp")
        meta["timestamp"] = aged
        meta_path.write_text(json.dumps(meta))

        age = fetcher.get_cached_age(URL)
        assert age is not None and 500 < age < 700


class TestTempFilesAreNotCacheEntries:
    def test_eviction_leaves_in_flight_writes_alone(self, monkeypatch):
        """`abc.html.tmpQ7z1`.split(".", 1)[0] is "abc", so a temp file grouped
        with the real entry and got unlinked mid-write — the writer's
        os.replace then raised FileNotFoundError."""
        _set_cache(URL, "<html>" + "x" * 500, "T")
        key = _cache_key(URL)
        tmp = fetcher.CACHE_DIR / f"{key}.html.tmpAbCdEf12"
        tmp.write_bytes(b"partially written")

        # Force the cap below the entry's size so eviction has to act.
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 1)
        monkeypatch.setattr(fetcher, "_last_sheet_evict", 0.0)
        fetcher._evict_sheet_cache()

        assert tmp.exists(), "an in-flight temp file must survive eviction"

    def test_clear_cache_leaves_in_flight_writes_alone(self):
        _set_cache(URL, "<html></html>", "T")
        tmp = fetcher.CACHE_DIR / f"{_cache_key(URL)}.html.tmpZzZzZz99"
        tmp.write_bytes(b"partial")

        cleared, _ = fetcher.clear_cache()
        assert cleared >= 1
        assert tmp.exists()

    def test_a_real_entry_is_still_evictable(self, monkeypatch):
        """Guard against the skip being too broad."""
        _set_cache(URL, "<html>" + "x" * 500, "T")
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 1)
        monkeypatch.setattr(fetcher, "_last_sheet_evict", 0.0)
        fetcher._evict_sheet_cache()
        assert not (fetcher.CACHE_DIR / f"{_cache_key(URL)}.html").exists()
