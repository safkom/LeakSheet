"""Parse-layer tests over the DMCA-safe synthetic fixtures.

These drive the real ``parse_sheet`` / ``parse_misc_tab`` / ``parse_art_tab`` on
committed, invented-content HTML that reproduces real tracker grammar, then pin
exact counts and attribute assignments AND assert the unified ``_health``
invariants. Because the fixtures are committed and deterministic, this is the
authoritative parse gate that runs everywhere (including a clean checkout / CI),
replacing the old accuracy harnesses that needed the gitignored ``Trackers/``.
"""

from __future__ import annotations

import pytest

from src.models import Badge
from src.parser import apply_art_tab_images, parse_art_tab, parse_misc_tab, parse_sheet
from tests._health import assert_healthy
from tests.conftest import read_synthetic


@pytest.fixture(scope="module")
def main():
    return parse_sheet(read_synthetic("main_tab"), "SynthWave")


# ---------------------------------------------------------------------------
# Main tab — counts, row accounting, and attribute assignment
# ---------------------------------------------------------------------------

class TestMainTabCounts:
    def test_era_song_version_counts(self, main):
        assert len(main.eras) == 2
        assert main.total_songs == 4
        assert main.total_versions == 5

    def test_row_accounting_identity(self, main):
        md = main.parse_metadata
        assert (md.total_rows, md.song_rows, md.skipped_rows, md.footer_rows, md.other_rows) == (
            9, 5, 0, 1, 3
        )
        # total == song + skipped + footer + other, with nothing dropped.
        assert md.total_rows == md.song_rows + md.skipped_rows + md.footer_rows + md.other_rows
        assert md.dropped_columns == []
        assert md.skipped_rows == 0

    def test_passes_health_invariants(self, main):
        assert_healthy(main)

    def test_tracker_stats(self, main):
        assert main.tracker_stats is not None
        assert main.tracker_stats.total_links == 3
        assert main.tracker_stats.total_full == 3


class TestMainTabAttributes:
    def test_debut_era_shape(self, main):
        debut = main.eras[0]
        assert debut.name == "Debut Era"
        assert [s.base_name for s in debut.songs] == ["Sunrise", "Nightfall", "Echoes"]

    def test_badge_quality_and_color(self, main):
        sunrise = main.eras[0].songs[0]
        v = sunrise.primary
        assert sunrise.badge == Badge.BEST          # ⭐ prefix
        assert v.quality == "High Quality"
        assert v.quality_color == "#4caf50"          # from the .s10 CSS class
        assert v.available_length == "Full"
        assert v.track_length == "3:14"
        assert v.leak_date == "2019-01-01"
        assert v.links == ["https://pillows.su/f/abc123"]

    def test_og_filename_extracted_and_stripped(self, main):
        v = main.eras[0].songs[0].primary
        assert v.og_filename == "sunrise_master"
        assert v.og_filenames == ["sunrise_master"]
        # The OG line is lifted into the structured field, not left in notes.
        assert v.notes is None

    def test_version_tag_grouping(self, main):
        nightfall = main.eras[0].songs[1]
        assert nightfall.base_name == "Nightfall"
        assert [v.version_tag for v in nightfall.versions] == ["V1", "V2"]

    def test_google_redirect_link_cleaned(self, main):
        # Nightfall V1's link was wrapped in a google.com/url?q= redirect.
        v1 = main.eras[0].songs[1].versions[0]
        assert v1.links == ["https://pillows.su/f/night1"]

    def test_feat_credit_and_sample(self, main):
        echoes = main.eras[0].songs[2]
        v = echoes.primary
        assert v.name == "Echoes"
        assert v.featuring == "Nova"
        assert v.samples == ["Clair de Lune — Debussy"]

    def test_section_separator_becomes_named_section(self, main):
        soph = main.eras[1]
        assert soph.name == "Sophomore Era"
        assert [sec.name for sec in soph.sections] == ["Features"]
        guest = soph.songs[0]
        assert guest.base_name == "Guest Spot"
        assert guest.primary.featuring == "Aurora"


# ---------------------------------------------------------------------------
# Travis-style tab — compound availability + Sources column, no Quality column
# ---------------------------------------------------------------------------

class TestCompoundAvailability:
    @pytest.fixture(scope="class")
    def travis(self):
        return parse_sheet(read_synthetic("travis_style"), "Astro")

    def test_no_quality_column_folds_into_availability(self, travis):
        stay = next(
            v for era in travis.eras for song in era.songs
            for v in song.versions if v.name.startswith("$tay")
        )
        assert stay.available_length == "Full (Unofficial)"
        assert stay.quality == "High Quality"
        assert stay.rating == 4
        # The compound markers must not remain in the availability string.
        assert "- HQ" not in (stay.available_length or "")

    def test_sources_extracted_with_labels_and_cleaned(self, travis):
        stay = next(
            v for era in travis.eras for song in era.songs
            for v in song.versions if v.name.startswith("$tay")
        )
        assert len(stay.sources) == 1
        src = stay.sources[0]
        assert src.label == "Trailer (YouTube)"
        assert "youtube.com" in src.url
        assert not src.url.startswith("https://www.google.com/url")

    def test_lq_marker_parsed(self, travis):
        antidote = next(
            v for era in travis.eras for song in era.songs
            for v in song.versions if v.name == "Antidote"
        )
        assert antidote.available_length == "Snippet"
        assert antidote.quality == "Low Quality"
        assert antidote.rating is None


# ---------------------------------------------------------------------------
# Misc + Art tabs
# ---------------------------------------------------------------------------

class TestMiscTab:
    @pytest.fixture(scope="class")
    def misc(self):
        return parse_misc_tab(read_synthetic("misc_tab"), "misc")

    def test_entries_parsed(self, misc):
        assert [m.name for m in misc] == ["Music Video One", "Interview Clip"]
        assert all(m.era_name == "Debut Era" for m in misc)
        assert all(m.source_tab == "misc" for m in misc)

    def test_fields_and_streaming_flag(self, misc):
        mv, interview = misc
        assert mv.entry_type == "Video"
        assert mv.date == "2020-01-01"
        assert mv.streaming is True
        assert mv.links == ["https://youtube.com/watch?v=vid1"]
        assert interview.streaming is False


class TestArtTab:
    @pytest.fixture(scope="class")
    def art_map(self):
        return parse_art_tab(read_synthetic("art_tab"))

    def test_art_map_keyed_by_era(self, art_map):
        assert art_map == {
            "debut era": "https://lh3.googleusercontent.com/debut-hq",
            "sophomore era": "https://lh3.googleusercontent.com/soph-hq",
        }

    def test_apply_upgrades_era_art(self, art_map):
        artist = parse_sheet(read_synthetic("main_tab"), "SynthWave")
        assert all(e.art_url is None for e in artist.eras)  # main tab has no art
        apply_art_tab_images(artist, art_map)
        assert artist.eras[0].art_url == "https://lh3.googleusercontent.com/debut-hq"
        assert artist.eras[1].art_url == "https://lh3.googleusercontent.com/soph-hq"


# ---------------------------------------------------------------------------
# Empty / malformed input must not crash
# ---------------------------------------------------------------------------

class TestDegenerateInput:
    def test_empty_html_yields_empty_artist(self):
        artist = parse_sheet("", "Nobody")
        assert artist.eras == []
        assert artist.total_songs == 0

    def test_no_table_yields_empty_artist(self):
        artist = parse_sheet("<html><body><p>no tables here</p></body></html>", "Nobody")
        assert artist.eras == []

    def test_misc_tab_without_header_returns_empty(self):
        assert parse_misc_tab("<html><body>nope</body></html>", "misc") == []
