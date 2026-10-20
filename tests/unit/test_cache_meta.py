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
from src.fetcher import _cache_key, _set_cache, _set_cached_parsed
from src.models import Artist, Era, Section, Song, SongVersion


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "CACHE_DIR", tmp_path)
    return tmp_path


def _artist(name: str = "SynthWave") -> Artist:
    song = Song(base_name="Intro", versions=[SongVersion(name="Intro")])
    return Artist(
        name=name, slug=name.lower(), eras=[Era(name="Era", sections=[Section(songs=[song])])]
    )


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

    def test_clear_cache_keeps_the_cross_worker_lock_files(self):
        # Unlinking a held *.meta.lock lets another worker flock a fresh file and
        # interleave a parsed body with the other's content_hash.
        _set_cache(URL, "<html></html>", "T")
        lock = fetcher.CACHE_DIR / f"{_cache_key(URL)}.meta.lock"
        assert lock.exists()

        fetcher.clear_cache()
        assert lock.exists()
        assert not (fetcher.CACHE_DIR / f"{_cache_key(URL)}.html").exists()

    def test_a_real_entry_is_still_evictable(self, monkeypatch):
        """Guard against the skip being too broad."""
        _set_cache(URL, "<html>" + "x" * 500, "T")
        monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 1)
        monkeypatch.setattr(fetcher, "_last_sheet_evict", 0.0)
        fetcher._evict_sheet_cache()
        assert not (fetcher.CACHE_DIR / f"{_cache_key(URL)}.html").exists()


class TestCollapseGuard:
    """A partial fetch parses cleanly and looks like any other result, so it
    used to be cached and then served by stale-while-revalidate until someone
    forced a refresh. Ye sat at 5,817 tracks / 36 eras for exactly that reason
    while a fresh parse of the same URL gave 9,382 / 44.
    """

    @staticmethod
    def _artist_with(versions: int, eras: int = 4) -> Artist:
        from src.models import Era, Section, Song, SongVersion
        per_era = max(1, versions // max(1, eras))
        built, remaining = [], versions
        for i in range(eras):
            take = per_era if i < eras - 1 else remaining
            remaining -= take
            songs = [
                Song(base_name=f"s{i}-{n}", versions=[SongVersion(name=f"s{i}-{n}")])
                for n in range(take)
            ]
            built.append(Era(name=f"Era {i}", sections=[Section(songs=songs)]))
        return Artist(name="Ye", slug="ye", eras=built)

    def _cached_versions(self, tmp_path) -> int:
        raw = json.loads((tmp_path / f"{_cache_key(URL)}.parsed.json").read_text())
        return raw["total_versions"]

    def test_a_collapsed_parse_does_not_overwrite_a_good_one(self, tmp_path):
        _set_cached_parsed(URL, self._artist_with(100))
        _set_cached_parsed(URL, self._artist_with(40))
        assert self._cached_versions(tmp_path) == 100

    def test_a_modest_shrink_is_a_real_edit_and_is_written(self, tmp_path):
        # Trackers lose tracks legitimately (DMCA, restructure); only a
        # collapse past the ratio is treated as a partial fetch.
        _set_cached_parsed(URL, self._artist_with(100))
        _set_cached_parsed(URL, self._artist_with(90))
        assert self._cached_versions(tmp_path) == 90

    def test_growth_is_always_written(self, tmp_path):
        _set_cached_parsed(URL, self._artist_with(100))
        _set_cached_parsed(URL, self._artist_with(160))
        assert self._cached_versions(tmp_path) == 160

    def test_the_first_parse_is_always_written(self, tmp_path):
        _set_cached_parsed(URL, self._artist_with(10))
        assert self._cached_versions(tmp_path) == 10

    @pytest.mark.parametrize(
        ("age_hours", "kept"), [(23, 100), (25, 40)],
    )
    def test_the_guard_window_is_24h_not_the_serve_window(self, tmp_path, age_hours, kept):
        """A 25 h entry is still served (SERVE_STALE_TTL is a week), but it no
        longer outranks a smaller fresh parse."""
        _set_cached_parsed(URL, self._artist_with(100))
        meta_file = tmp_path / f"{_cache_key(URL)}.meta.json"
        meta = json.loads(meta_file.read_text())
        meta["parsed_timestamp"] = time.time() - age_hours * 3600
        meta_file.write_text(json.dumps(meta))

        _set_cached_parsed(URL, self._artist_with(40))
        assert self._cached_versions(tmp_path) == kept

    def test_a_genuinely_shrunken_tracker_recovers_once_the_entry_is_stale(self, tmp_path):
        """The guard prefers the old copy only inside COLLAPSE_GUARD_TTL (24 h).
        Past it a smaller parse must win, or a tracker that really shrank is
        frozen for as long as the old entry is served."""
        _set_cached_parsed(URL, self._artist_with(100))
        key = _cache_key(URL)
        meta_file = tmp_path / f"{key}.meta.json"
        meta = json.loads(meta_file.read_text())
        meta["parsed_timestamp"] = time.time() - (fetcher.COLLAPSE_GUARD_TTL + 60)
        meta_file.write_text(json.dumps(meta))

        _set_cached_parsed(URL, self._artist_with(40))
        assert self._cached_versions(tmp_path) == 40

    def _age_entry(self, tmp_path, seconds: float) -> None:
        meta_file = tmp_path / f"{_cache_key(URL)}.meta.json"
        meta = json.loads(meta_file.read_text())
        meta["parsed_timestamp"] = time.time() - seconds
        meta_file.write_text(json.dumps(meta))

    @pytest.mark.parametrize(("failed_tabs", "kept"), [(1, 100), (0, 40)])
    def test_failed_tabs_extend_the_guard_to_the_serve_window(self, tmp_path, failed_tabs, kept):
        """Entries up to SERVE_STALE_TTL are served, so a partial parse of a 3-day-old
        entry must not replace it; a parse with every tab loaded is a real shrink."""
        _set_cached_parsed(URL, self._artist_with(100))
        self._age_entry(tmp_path, 3 * 86400)

        _set_cached_parsed(URL, self._artist_with(40), failed_tabs=failed_tabs)
        assert self._cached_versions(tmp_path) == kept

    def test_a_permanently_failing_tab_cannot_freeze_an_entry_past_the_serve_window(
        self, tmp_path
    ):
        _set_cached_parsed(URL, self._artist_with(100))
        self._age_entry(tmp_path, fetcher.SERVE_STALE_TTL + 60)

        _set_cached_parsed(URL, self._artist_with(40), failed_tabs=1)
        assert self._cached_versions(tmp_path) == 40


class TestEmptyParseIsNeverCached:
    """A parse with no tracks is a failed load, not a tracker: cached, it is served as a
    hit for an hour and the app caches it too. The check sits before the no-entry early
    return so every write path is covered at once."""

    @staticmethod
    def _empty() -> Artist:
        return Artist(name="Ye", slug="ye", eras=[])

    def test_not_written_when_no_entry_exists(self, tmp_path):
        artist = self._empty()
        _set_cached_parsed(URL, artist)
        assert not (tmp_path / f"{_cache_key(URL)}.parsed.json").exists()
        assert artist._wire is None

    def test_eras_without_songs_are_empty_too(self, tmp_path):
        # A hub tab parses to eras with no songs.
        _set_cached_parsed(URL, Artist(name="Ye", slug="ye", eras=[Era(name="Index", sections=[])]))
        assert not (tmp_path / f"{_cache_key(URL)}.parsed.json").exists()

    def test_does_not_replace_a_good_entry(self, tmp_path):
        _set_cached_parsed(URL, TestCollapseGuard._artist_with(100))
        _set_cached_parsed(URL, self._empty())
        raw = json.loads((tmp_path / f"{_cache_key(URL)}.parsed.json").read_text())
        assert raw["total_versions"] == 100

    def test_does_not_replace_an_entry_past_the_stale_window(self, tmp_path):
        # The collapse ratio stands down for an old entry; emptiness never does.
        _set_cached_parsed(URL, TestCollapseGuard._artist_with(100))
        meta_file = tmp_path / f"{_cache_key(URL)}.meta.json"
        meta = json.loads(meta_file.read_text())
        meta["parsed_timestamp"] = time.time() - (fetcher.COLLAPSE_GUARD_TTL + 60)
        meta_file.write_text(json.dumps(meta))

        _set_cached_parsed(URL, self._empty())
        raw = json.loads((tmp_path / f"{_cache_key(URL)}.parsed.json").read_text())
        assert raw["total_versions"] == 100


class TestDropCachedEntry:
    """A source that is gone must stop being served: the HTML, the parse and the
    metadata all go, so nothing is served or kept as a collapse baseline."""

    OTHER = "https://example.com/other"

    def _files(self, tmp_path, url):
        return sorted(p.name for p in tmp_path.glob(f"{_cache_key(url)}.*") if p.suffix != ".lock")

    def test_drops_the_html_parse_and_meta(self, tmp_path):
        _set_cache(URL, "<html></html>", "T")
        _set_cached_parsed(URL, _artist())
        assert len(self._files(tmp_path, URL)) == 3

        fetcher.drop_cached_entry(URL)

        assert self._files(tmp_path, URL) == []
        assert fetcher.get_cached_parsed_bytes(URL) is None
        assert fetcher.get_cached_etag(URL) is None
        assert fetcher.get_cached_age(URL) is None

    def test_leaves_other_trackers_and_tolerates_a_missing_entry(self, tmp_path):
        _set_cached_parsed(self.OTHER, _artist("Other"))
        fetcher.drop_cached_entry(URL)  # nothing cached: no error
        fetcher.drop_cached_entry(URL)
        assert len(self._files(tmp_path, self.OTHER)) == 2
        assert fetcher.get_cached_parsed_bytes(self.OTHER) is not None

    def test_a_dropped_entry_is_no_collapse_baseline(self, tmp_path):
        _set_cached_parsed(URL, TestCollapseGuard._artist_with(100))
        fetcher.drop_cached_entry(URL)
        _set_cached_parsed(URL, TestCollapseGuard._artist_with(40))
        assert fetcher.get_cached_parsed_bytes(URL) is not None


class TestTabOnlyTrackerIsServable:
    """A tracker with content tabs but no songs is a real tracker; an empty one is not."""

    def test_tab_entries_make_a_songless_entry_servable(self):
        from src.models import MiscEntry, TabSection

        artist = _artist()
        artist.eras = []
        artist.tabs = [TabSection(kind="misc", name="Misc", entries=[MiscEntry(name="x", source_tab="misc")])]
        _set_cached_parsed(URL, artist)
        assert fetcher.get_cached_etag(URL) is not None
        assert fetcher.get_cached_parsed_bytes(URL) is not None

    def test_a_truly_empty_entry_stays_unservable(self):
        artist = _artist()
        artist.eras = []
        _set_cached_parsed(URL, artist)
        assert fetcher.get_cached_etag(URL) is None
