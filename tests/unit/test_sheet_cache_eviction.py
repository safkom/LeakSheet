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


def _touch(path, *, age_s: float) -> None:
    path.write_bytes(b"x")
    mtime = time.time() - age_s
    os.utime(path, (mtime, mtime))


class TestAbandonedFileSweep:
    """Files no size cap ever counted: a killed worker's temp files and cover aliases
    whose token URL no parse has produced in weeks."""

    def test_orphaned_temp_files_are_aged_out(self, _isolate_cache):
        cache_dir = _isolate_cache
        orphan = cache_dir / ("a" * 64 + ".html.tmpAbCdEf12")
        img_orphan = cache_dir / "img_deadbeef.bin.tmpQwErTy34"
        in_flight = cache_dir / ("b" * 64 + ".parsed.json.tmpZxCvBn56")
        _touch(orphan, age_s=2 * 3600)
        _touch(img_orphan, age_s=2 * 3600)
        _touch(in_flight, age_s=5)

        fetcher._evict_sheet_cache()

        assert not orphan.exists()
        assert not img_orphan.exists()
        assert in_flight.exists()

    def test_stale_cover_aliases_are_swept(self, _isolate_cache):
        import src.api as api

        cache_dir = _isolate_cache
        stale = cache_dir / "imgalias_old.txt"
        live = cache_dir / "imgalias_new.txt"
        _touch(stale, age_s=api._IMAGE_ALIAS_TTL + 60)
        _touch(live, age_s=60)

        api._evict_image_cache()

        assert not stale.exists()
        assert live.exists()


class TestEraOriginalBudget:
    """Era originals cannot be refetched once their token dies; variants can."""

    @staticmethod
    def _put(api, name, size, age_s, original):
        key = f"{name:0<8}"
        api._write_image_cache(key, b"x" * size, "image/png", original=original)
        bin_path, meta = api._image_cache_paths(key)
        t = time.time() - age_s
        os.utime(bin_path, (t, t))
        return bin_path, meta

    def test_pressure_drops_variants_and_keeps_older_originals(self, _isolate_cache, monkeypatch):
        import src.api as api

        monkeypatch.setattr(api, "_IMAGE_CACHE_MAX_BYTES", 250)
        monkeypatch.setattr(api, "_IMAGE_ORIGINALS_MAX_BYTES", 10_000)
        orig, _ = self._put(api, "a", 200, 1000, True)  # oldest
        var1, _ = self._put(api, "b", 200, 500, False)
        var2, _ = self._put(api, "c", 200, 100, False)

        api._evict_image_cache()

        assert orig.exists() and var2.exists() and not var1.exists()

    def test_originals_only_overflow_is_bounded_oldest_first(self, _isolate_cache, monkeypatch):
        import src.api as api

        monkeypatch.setattr(api, "_IMAGE_ORIGINALS_MAX_BYTES", 450)
        old, old_meta = self._put(api, "a", 200, 1000, True)
        mid, _ = self._put(api, "b", 200, 500, True)
        new, _ = self._put(api, "c", 200, 100, True)

        api._evict_image_cache()

        assert not old.exists() and not old_meta.exists()
        assert mid.exists() and new.exists()

    def test_legacy_original_without_flag_survives_via_its_alias(self, _isolate_cache, monkeypatch):
        import src.api as api

        monkeypatch.setattr(api, "_IMAGE_CACHE_MAX_BYTES", 250)
        base = "leaksheet:art/v2/" + "a" * 32 + "/" + "b" * 32
        api._write_image_alias("https://docs.google.com/sheets-images-rt/tok", base)
        legacy = api._image_cache_key(base, None)
        api._write_image_cache(legacy, b"x" * 200, "image/png")  # written the old way
        bin_path, _ = api._image_cache_paths(legacy)
        os.utime(bin_path, (1, 1))  # oldest
        var, _ = self._put(api, "v", 200, 100, False)

        api._evict_image_cache()

        assert bin_path.exists() and var.exists()
