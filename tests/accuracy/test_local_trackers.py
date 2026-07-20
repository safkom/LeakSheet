"""Tracker-integration tests against the LOCAL, gitignored Trackers/ dumps.

Extracted from the old tests/test_parser.py — everything here needs the real
downloaded tracker HTML (``discover_trackers()``), which is gitignored for DMCA
reasons and absent on a clean checkout / CI. The whole module is therefore
marked ``accuracy`` and skipped when those dumps aren't present. Run it locally
with:

    pytest -m accuracy

The pure-logic tests these were mixed with now live in tests/unit/test_parser_units.py
and run everywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import TRACKERS_DIR, discover_trackers
from src.models import Badge
from src.parser import detect_columns, extract_table, parse_file

_TRACKERS = dict(discover_trackers())
_KNOWN = {"Ye", "Kendrick Lamar", "Baby Keem", "Playboi Carti"}

pytestmark = [
    pytest.mark.accuracy,
    pytest.mark.skipif(
        not _KNOWN <= set(_TRACKERS),
        reason="local Trackers/ dumps not present (gitignored; regenerate to run -m accuracy)",
    ),
]


@pytest.fixture(scope="module")
def all_artists():
    return {name: parse_file(path, name) for name, path in discover_trackers()}


@pytest.fixture(scope="module")
def ye(all_artists):
    return all_artists["Ye"]


@pytest.fixture(scope="module")
def kendrick(all_artists):
    return all_artists["Kendrick Lamar"]


@pytest.fixture(scope="module")
def keem(all_artists):
    return all_artists["Baby Keem"]


@pytest.fixture(scope="module")
def carti(all_artists):
    return all_artists["Playboi Carti"]


class TestColumnDetection:
    def test_ye_columns(self, ye):
        html = (TRACKERS_DIR / "Ye Tracker - Google Drive_files" / "sheet.html").read_text(encoding="utf-8")
        col_map = detect_columns(extract_table(html)[0])
        for key in ("era", "name", "notes", "track_length", "file_date", "leak_date",
                    "available_length", "quality", "links"):
            assert key in col_map

    def test_carti_columns(self, carti):
        html = (TRACKERS_DIR / "Playboi Carti Tracker [Currently in Use] - Google Drive_files" / "sheet.html").read_text(encoding="utf-8")
        col_map = detect_columns(extract_table(html)[0])
        assert "date_of_recording" in col_map and "type" in col_map and "notes" in col_map


class TestAllTrackers:
    def test_all_four_trackers_discovered(self, all_artists):
        assert _KNOWN <= set(all_artists)

    def test_every_artist_has_eras(self, all_artists):
        for name, artist in all_artists.items():
            assert len(artist.eras) > 0, f"{name} has no eras"

    def test_every_artist_has_songs(self, all_artists):
        for name, artist in all_artists.items():
            assert artist.total_songs > 0, f"{name} has no songs"

    def test_slug_is_lowercase(self, all_artists):
        for artist in all_artists.values():
            assert artist.slug == artist.slug.lower() and " " not in artist.slug


class TestYeTracker:
    def test_era_count(self, ye):
        assert ye.total_songs > 3000 and len(ye.eras) >= 40

    def test_yeezus_2_song_count(self, ye):
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        assert era.song_count >= 130

    def test_about_time_metadata(self, ye):
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        song = next(s for s in era.songs if s.base_name == "About Time")
        v = song.versions[0]
        assert v.track_length == "0:42"
        assert v.available_length == "OG File"
        assert v.quality == "Lossless"
        assert v.leak_date == "Mar 20, 2023"
        assert v.file_date == "Nov 11, 2013"

    def test_star_badge_parsed(self, ye):
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        song = next(s for s in era.songs if "Black Skinhead" in s.base_name and "Remix" in s.base_name)
        assert any(v.badge == Badge.BEST for v in song.versions if v.version_tag == "V3")

    def test_donda_era_exists(self, ye):
        assert any("donda" in e.name.lower() for e in ye.eras)


class TestKendrickTracker:
    def test_counts(self, kendrick):
        assert len(kendrick.eras) >= 15 and kendrick.total_songs >= 500

    def test_tpab_era_exists(self, kendrick):
        assert any("Pimp" in n and "Butterfly" in n for n in (e.name for e in kendrick.eras))


class TestBabyKeemTracker:
    def test_counts(self, keem):
        assert len(keem.eras) >= 5 and keem.total_songs >= 150

    def test_the_melodic_blue(self, keem):
        assert sum("Melodic Blue" in e.name for e in keem.eras) == 1


class TestCartiTracker:
    def test_counts(self, carti):
        assert len(carti.eras) >= 10 and carti.total_songs >= 400

    def test_carti_specific_fields(self, carti):
        vs = [v for era in carti.eras for s in era.songs for v in s.versions]
        assert any(v.type for v in vs) and any(v.date_of_recording for v in vs)


class TestNoteLinksMerge:
    def test_kendrick_note_only_link(self, kendrick):
        song = next((s for era in kendrick.eras for s in era.songs if s.base_name == "Hotel Paranoia"), None)
        assert song is not None
        links = song.versions[0].links
        assert links and any("youtube.com" in lnk for lnk in links)

    def test_total_links_increased_for_kendrick(self, kendrick):
        total = sum(len(v.links) for era in kendrick.eras for s in era.songs for v in s.versions)
        assert total >= 735


class TestVersionTagGrouping:
    def test_carti_cd_version_tag_parsed(self, carti):
        assert any(
            v.version_tag and v.version_tag.upper() == "CD VERSION"
            for era in carti.eras for s in era.songs for v in s.versions
        )

    def test_ye_album_tag_parsed(self, ye):
        assert any(
            v.version_tag and v.version_tag.lower() == "album"
            for era in ye.eras for s in era.songs for v in s.versions
        )


class TestZeroEraRegression:
    def test_keem_all_eras_have_songs(self, keem):
        zero = [e.name for e in keem.eras if e.song_count == 0]
        assert zero == []

    def test_kendrick_most_eras_have_songs(self, kendrick):
        zero = [e.name for e in kendrick.eras if e.song_count == 0]
        assert len(zero) <= 2


class TestEraStatsOnData:
    def test_ye_eras_have_stats(self, ye):
        for era in ye.eras:
            assert era.stats is not None, f"Era {era.name!r} has no parsed stats"

    def test_ye_total_from_era_stats(self, ye):
        era_sum = sum(e.stats.total for e in ye.eras if e.stats)
        assert abs(era_sum - ye.total_versions) < 50


class TestTrackerStatsOnData:
    def test_ye_has_tracker_stats(self, ye):
        assert ye.tracker_stats is not None and ye.tracker_stats.total_links > 1000

    def test_keem_has_tracker_stats(self, keem):
        assert keem.tracker_stats is not None and keem.tracker_stats.total_links > 100


class TestFooterDetection:
    def test_kendrick_last_era_not_inflated(self, kendrick):
        for song in kendrick.eras[-1].songs:
            for v in song.versions:
                assert "Tracker Guidelines" not in v.name
                assert "Changelogs" not in v.name


class TestSongCreditsOnData:
    def test_ye_songs_have_producers(self, ye):
        assert sum(1 for era in ye.eras for s in era.songs for v in s.versions if v.producers) > 100

    def test_ye_10_in_a_benz_credits(self, ye):
        era = next(e for e in ye.eras if "Before The College Dropout" in e.name)
        v = next(s for s in era.songs if s.base_name == "10 in a Benz").versions[0]
        assert v.featuring == "Rhymefest"
        assert v.producers == "Kanye West & Andy C."
        assert v.collaboration == "Go Getters"

    def test_song_name_is_clean_title(self, ye):
        era = next(e for e in ye.eras if "Before The College Dropout" in e.name)
        v = next(s for s in era.songs if s.base_name == "10 in a Benz").versions[0]
        assert "\n" not in v.name and "(prod." not in v.name and "(feat." not in v.name


class TestEraTimelineAndDescription:
    def test_ye_first_era_has_timeline(self, ye):
        era = ye.eras[0]
        assert len(era.timeline) >= 2 and era.timeline[0].date == "06/08/1977"

    def test_all_eras_timeline_is_list(self, ye, keem, kendrick, carti):
        for artist in (ye, keem, kendrick, carti):
            for era in artist.eras:
                assert isinstance(era.timeline, list)


class TestSectionAndStubHandling:
    def test_notes_column_section_label(self, all_artists):
        result = all_artists["Playboi Carti"]
        assert result.parse_metadata.skipped_rows == 0, result.parse_metadata.unmatched_rows
        labels = {lbl for era in result.eras for sec in era.sections for lbl in (sec.name, sec.group) if lbl}
        assert "WLR Higher Bitrate Files" in labels
        assert "Festival Remixes" in labels

    def test_tmb_collab_stub_merged(self, all_artists):
        result = all_artists["Playboi Carti"]
        unmerged = [
            e for e in result.eras
            if e.name.startswith("Collaboration with ") and e.song_count == 0
        ]
        assert unmerged == []

    def test_carti_tracker_hub_not_a_section(self, all_artists):
        result = all_artists["Playboi Carti"]
        for era in result.eras:
            for sec in era.sections:
                assert "carti tracker hub" not in sec.name.lower()


# ---------------------------------------------------------------------------
# Misc/Music-Video tab parsing against the (untracked, on-disk) Kendrick dumps.
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.mark.skipif(
    not (_FIXTURES / "kendrick_misc_tab.html").exists(),
    reason="kendrick_*_tab.html dumps not present (gitignored)",
)
class TestParseMiscTabRealDumps:
    @staticmethod
    def _fixture(name):
        return (_FIXTURES / name).read_text(encoding="utf-8")

    def test_music_videos_fixture(self):
        from src.parser import parse_misc_tab
        entries = parse_misc_tab(self._fixture("kendrick_music_videos_tab.html"), "music_videos")
        assert len(entries) == 107
        first = entries[0]
        assert first.era_name == "C4"
        assert first.name.startswith("Jay Rock - What's Up")
        assert first.streaming is False
        assert all(e.source_tab == "music_videos" for e in entries)

    def test_misc_fixture(self):
        from src.parser import parse_misc_tab
        entries = parse_misc_tab(self._fixture("kendrick_misc_tab.html"), "misc")
        assert len(entries) == 69
        freestyle = next(e for e in entries if e.name == "XXL Freshman Freestyle")
        assert freestyle.era_name == "Section.80"
        assert freestyle.available == "Full"
        assert freestyle.quality == "High Quality"
