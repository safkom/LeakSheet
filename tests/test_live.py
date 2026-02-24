"""Live URL tests — verify parsing against real Google Sheets data.

Run with: python3 -m pytest tests/test_live.py -v -m live
These tests require network access and hit live Google Sheets URLs.

Local tests (test_parser.py) remain for fast regression testing.
Live tests verify completeness: all eras have art, stats match, no silent data loss.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from src.config import TRACKERS_DIR
from src.fetcher import fetch_and_parse


# Mark all tests in this module as 'live' so they can be selected/excluded
pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Fixtures — fetch once per module (expensive network calls)
# ---------------------------------------------------------------------------

def _read_links() -> list[str]:
    """Read tracker URLs from links.txt."""
    links_path = TRACKERS_DIR / "links.txt"
    if not links_path.exists():
        return []
    return [
        line.strip()
        for line in links_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


@pytest.fixture(scope="module")
def live_artists():
    """Fetch and parse all live tracker URLs."""
    urls = _read_links()
    if not urls:
        pytest.skip("No URLs in links.txt")
    results = {}
    for url in urls:
        artist = fetch_and_parse(url)
        results[artist.slug] = artist
    return results


@pytest.fixture(scope="module")
def ye_live(live_artists):
    return live_artists.get("ye")


@pytest.fixture(scope="module")
def kendrick_live(live_artists):
    return live_artists.get("kendrick-lamar")


@pytest.fixture(scope="module")
def keem_live(live_artists):
    return live_artists.get("baby-keem")


@pytest.fixture(scope="module")
def carti_live(live_artists):
    return live_artists.get("playboi-carti")


# ---------------------------------------------------------------------------
# Structural completeness — every tracker
# ---------------------------------------------------------------------------

class TestLiveStructure:
    """Basic structural checks on live-fetched data."""

    def test_all_trackers_loaded(self, live_artists):
        assert len(live_artists) >= 4, f"Expected >=4 artists, got {len(live_artists)}"

    def test_every_artist_has_eras(self, live_artists):
        for slug, artist in live_artists.items():
            assert len(artist.eras) > 0, f"{artist.name} has no eras"

    def test_every_artist_has_songs(self, live_artists):
        for slug, artist in live_artists.items():
            assert artist.total_songs > 0, f"{artist.name} has no songs"

    def test_source_url_set(self, live_artists):
        for slug, artist in live_artists.items():
            assert artist.source_url is not None, f"{artist.name} missing source_url"


# ---------------------------------------------------------------------------
# Parse metadata — no silent data loss
# ---------------------------------------------------------------------------

class TestParseMetadata:
    """Verify parse metadata is populated and skipped rows are minimal."""

    def test_metadata_exists(self, live_artists):
        for slug, artist in live_artists.items():
            assert artist.parse_metadata is not None, (
                f"{artist.name} has no parse_metadata"
            )

    def test_song_rows_positive(self, live_artists):
        for slug, artist in live_artists.items():
            meta = artist.parse_metadata
            assert meta.song_rows > 0, f"{artist.name}: 0 song_rows parsed"

    def test_skipped_rows_low(self, live_artists):
        """Skipped rows should be < 5% of total rows."""
        for slug, artist in live_artists.items():
            meta = artist.parse_metadata
            if meta.total_rows == 0:
                continue
            skip_pct = meta.skipped_rows / meta.total_rows
            assert skip_pct < 0.05, (
                f"{artist.name}: {meta.skipped_rows}/{meta.total_rows} rows skipped "
                f"({skip_pct:.1%}). Unmatched: {meta.unmatched_rows[:5]}"
            )


# ---------------------------------------------------------------------------
# Era art — live trackers should have art for most eras
# ---------------------------------------------------------------------------

class TestLiveEraArt:
    """Live trackers have more images than local HTML exports."""

    def test_ye_most_eras_have_art(self, ye_live):
        if ye_live is None:
            pytest.skip("Ye not loaded")
        eras_with_art = [e for e in ye_live.eras if e.art_url]
        ratio = len(eras_with_art) / len(ye_live.eras) if ye_live.eras else 0
        assert ratio > 0.5, (
            f"Only {len(eras_with_art)}/{len(ye_live.eras)} Ye eras have art"
        )

    def test_keem_most_eras_have_art(self, keem_live):
        if keem_live is None:
            pytest.skip("Baby Keem not loaded")
        eras_with_art = [e for e in keem_live.eras if e.art_url]
        assert len(eras_with_art) >= len(keem_live.eras) // 2


# ---------------------------------------------------------------------------
# Era stats consistency — parsed counts should match song counts
# ---------------------------------------------------------------------------

class TestLiveEraStats:
    """Verify era stats totals are close to actual parsed song counts."""

    def test_ye_stats_consistency(self, ye_live):
        if ye_live is None:
            pytest.skip("Ye not loaded")
        era_stats_total = sum(e.stats.total for e in ye_live.eras if e.stats)
        # Allow 10% discrepancy (sub-headers, stale metadata)
        assert abs(era_stats_total - ye_live.total_versions) < ye_live.total_versions * 0.1, (
            f"Ye: era stats sum {era_stats_total} vs parsed {ye_live.total_versions}"
        )

    def test_all_eras_have_stats(self, live_artists):
        for slug, artist in live_artists.items():
            for era in artist.eras:
                assert era.stats is not None, (
                    f"{artist.name} era '{era.name}' has no parsed stats"
                )


# ---------------------------------------------------------------------------
# Zero-song era check — no era should have 0 songs (live data should be complete)
# ---------------------------------------------------------------------------

class TestLiveZeroEras:
    """With live data, all eras should have songs."""

    def test_no_zero_song_eras(self, live_artists):
        for slug, artist in live_artists.items():
            zero_eras = [e for e in artist.eras if e.song_count == 0]
            # Allow at most 2 zero-song eras (known edge cases)
            assert len(zero_eras) <= 2, (
                f"{artist.name}: {len(zero_eras)} eras with 0 songs: "
                f"{[e.name for e in zero_eras]}"
            )
