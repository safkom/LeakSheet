"""Size-cap eviction for the sheet/parsed file cache (2026-07-20 review).

The image cache has had a 200MB cap for a while; the sheet HTML + parsed-JSON
cache had none — a TrackerHub sweep left ~700MB behind on a 512MB-class box.
Eviction drops the oldest cache entries (grouped by hash stem: .html,
.meta.json, .parsed.json together) until the total is under the cap, and
never touches the img_* files (they have their own eviction).
"""

from __future__ import annotations

import os
import time

import pytest

import src.fetcher as fetcher


def _make_entry(cache_dir, stem: str, *, size: int, age_s: float) -> None:
    mtime = time.time() - age_s
    for suffix, payload in (
        (".html", b"h" * size),
        (".meta.json", b'{"url": "https://x/%s"}' % stem.encode()),
        (".parsed.json", b"p" * size),
    ):
        p = cache_dir / f"{stem}{suffix}"
        p.write_bytes(payload)
        os.utime(p, (mtime, mtime))


class TestSheetCacheEviction:
    def test_oldest_groups_evicted_first(self, _isolate_cache, monkeypatch):
        cache_dir = _isolate_cache
        _make_entry(cache_dir, "a" * 64, size=600, age_s=3000)   # oldest
        _make_entry(cache_dir, "b" * 64, size=600, age_s=2000)
        _make_entry(cache_dir, "c" * 64, size=600, age_s=1000)   # newest
        # Cap fits roughly two entries (2 * (600+600) bytes + meta).
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 2600)

        fetcher._evict_sheet_cache()

        assert not (cache_dir / ("a" * 64 + ".html")).exists()
        assert not (cache_dir / ("a" * 64 + ".parsed.json")).exists()
        assert not (cache_dir / ("a" * 64 + ".meta.json")).exists()
        assert (cache_dir / ("b" * 64 + ".html")).exists()
        assert (cache_dir / ("c" * 64 + ".html")).exists()

    def test_groups_evicted_atomically(self, _isolate_cache, monkeypatch):
        cache_dir = _isolate_cache
        _make_entry(cache_dir, "a" * 64, size=1000, age_s=2000)
        _make_entry(cache_dir, "b" * 64, size=1000, age_s=1000)
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 2500)

        fetcher._evict_sheet_cache()

        # Entry A vanishes wholesale — no orphan meta/parsed files remain.
        assert not list(cache_dir.glob("a" * 64 + "*"))
        assert len(list(cache_dir.glob("b" * 64 + "*"))) == 3

    def test_image_cache_files_untouched(self, _isolate_cache, monkeypatch):
        cache_dir = _isolate_cache
        img = cache_dir / "img_deadbeef.bin"
        img.write_bytes(b"i" * 5000)
        old = time.time() - 99999
        os.utime(img, (old, old))
        _make_entry(cache_dir, "a" * 64, size=1000, age_s=10)
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 100)

        fetcher._evict_sheet_cache()

        assert img.exists()  # image cache has its own cap/eviction

    def test_under_cap_is_noop(self, _isolate_cache, monkeypatch):
        cache_dir = _isolate_cache
        _make_entry(cache_dir, "a" * 64, size=10, age_s=100)
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 10_000_000)

        fetcher._evict_sheet_cache()

        assert len(list(cache_dir.glob("a" * 64 + "*"))) == 3

    def test_set_cache_triggers_throttled_eviction(self, _isolate_cache, monkeypatch):
        cache_dir = _isolate_cache
        _make_entry(cache_dir, "a" * 64, size=5000, age_s=5000)
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 1000)
        monkeypatch.setattr(fetcher, "_last_sheet_evict", 0.0)

        fetcher._set_cache("https://example.test/tracker", "<html></html>", "T")

        # The old oversized entry was evicted by the write hook…
        assert not list(cache_dir.glob("a" * 64 + "*"))
        # …and the throttle timestamp advanced.
        assert fetcher._last_sheet_evict > 0.0
