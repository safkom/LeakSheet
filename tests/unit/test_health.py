"""Unit tests for the shared parse-health module (tests/_health.py)."""

from __future__ import annotations

from src.models import Artist, Era, EraStats, ParseMetadata, Section, Song, SongVersion
from tests._health import health_violations, live_violations


def _artist_with_starved_era(era_name: str) -> Artist:
    real = Era(name="Real Era", sections=[Section(songs=[
        Song(base_name="Song A", versions=[SongVersion(name="Song A")]),
    ])])
    starved = Era(name=era_name, stats=EraStats(full=2), sections=[Section()])
    return Artist(
        name="T", slug="t", eras=[real, starved],
        parse_metadata=ParseMetadata(
            total_rows=3, song_rows=1, skipped_rows=0, footer_rows=0,
            other_rows=2, unmatched_rows_total=0,
        ),
    )


class TestPlaceholderEraLeniency:
    def test_live_check_excuses_template_eras(self):
        # Template scaffolding ("TBA", "Album Name 4", "Unknown Eras",
        # "Ongoing") with dummy stats is data-side, not a parser bug —
        # live checks must not flag it (2026-07-20 sweep noise).
        for name in ("TBA", "Album Name 4", "Unknown Eras", "Ongoing", "tbd"):
            artist = _artist_with_starved_era(name)
            assert live_violations(artist) == [], name

    def test_live_check_still_flags_real_starved_eras(self):
        artist = _artist_with_starved_era("Get Rich Or Die Tryin' Soundtrack")
        violations = live_violations(artist)
        assert any("stats claim songs" in v for v in violations)

    def test_strict_check_keeps_flagging_placeholders(self):
        # Synthetic fixtures are fully controlled — a starved era there is a
        # bug regardless of its name.
        artist = _artist_with_starved_era("TBA")
        violations = health_violations(artist)
        assert any("stats claim songs" in v for v in violations)


class TestListenLinks:
    """A tracker whose listen links all landed in evidence parses cleanly but plays nothing."""

    @staticmethod
    def _artist(links: list[str], n: int = 30):
        from src.models import Artist, Era, Section, Song, SongVersion
        songs = [Song(base_name=f"S{i}", versions=[SongVersion(name=f"S{i}", links=links)]) for i in range(n)]
        return Artist(name="T", slug="t", eras=[Era(name="E", sections=[Section(songs=songs)])])

    def test_a_tracker_with_no_listen_links_is_flagged(self):
        from tests._health import _link_column_violations
        assert _link_column_violations(self._artist([]))

    def test_links_on_an_unsupported_host_are_not_a_parse_break(self):
        from tests._health import _link_column_violations
        assert _link_column_violations(self._artist(["https://vault.example.test/a.mp3"])) == []

    def test_a_small_tracker_is_not_judged(self):
        from tests._health import _link_column_violations
        assert _link_column_violations(self._artist([], n=5)) == []
