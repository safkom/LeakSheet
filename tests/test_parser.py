"""Automated parser correctness tests.

Tests parser output against known ground-truth values extracted by
manually inspecting the tracker HTML files.
"""

import pytest
from pathlib import Path

from src.config import TRACKERS_DIR, discover_trackers
from src.parser import parse_file, detect_columns, extract_table, _era_match_key
from src.models import Badge, extract_badge, extract_version_tag


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_artists():
    """Parse all local trackers once for the module."""
    results = {}
    for artist_name, sheet_path in discover_trackers():
        from src.parser import parse_file
        results[artist_name] = parse_file(sheet_path, artist_name)
    return results


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


# ---------------------------------------------------------------------------
# Model unit tests
# ---------------------------------------------------------------------------

class TestExtractBadge:
    def test_star_badge(self):
        badge, name = extract_badge("⭐ Black Skinhead (Remix) [V3]")
        assert badge == Badge.BEST
        assert name == "Black Skinhead (Remix) [V3]"

    def test_sparkle_badge(self):
        badge, name = extract_badge("✨ After You [V7]")
        assert badge == Badge.SPECIAL
        assert name == "After You [V7]"

    def test_no_badge(self):
        badge, name = extract_badge("About Time")
        assert badge is None
        assert name == "About Time"

    def test_trophy_badge(self):
        badge, name = extract_badge("🏆 Some Grail")
        assert badge == Badge.GRAIL
        assert name == "Some Grail"

    def test_trash_badge(self):
        badge, name = extract_badge("🗑️ Bad Song")
        assert badge == Badge.WORST
        assert name == "Bad Song"


class TestExtractVersionTag:
    def test_simple_v1(self):
        tag, base = extract_version_tag("Afta U [V1]")
        assert tag == "V1"
        assert base == "Afta U"

    def test_v_range(self):
        tag, base = extract_version_tag("Something [V2-V25]")
        assert tag == "V2-V25"
        assert base == "Something"

    def test_alt_tag(self):
        tag, base = extract_version_tag("Song [Alt.]")
        assert tag == "Alt."
        assert base == "Song"

    def test_no_tag(self):
        tag, base = extract_version_tag("About Time")
        assert tag is None
        assert base == "About Time"

    def test_tag_with_parens_after(self):
        tag, base = extract_version_tag("After You [V2](prod. Dom $olo)")
        assert tag == "V2"
        assert base == "After You(prod. Dom $olo)"

    def test_master_tag(self):
        tag, base = extract_version_tag("Location [MASTER](prod. Harry Fraud)")
        assert tag == "MASTER"
        assert base == "Location(prod. Harry Fraud)"

    def test_cd_version_tag(self):
        tag, base = extract_version_tag("POP OUT [CD VERSION](prod. F1LTHY)")
        assert tag == "CD VERSION"
        assert base == "POP OUT(prod. F1LTHY)"

    def test_unknown_version_tag(self):
        tag, base = extract_version_tag("Red Lean [V?](feat. Lil Uzi Vert)")
        assert tag == "V?"
        assert base == "Red Lean(feat. Lil Uzi Vert)"

    def test_version_range_unknown_upper(self):
        tag, base = extract_version_tag("DRONES. [V1-V?](prod. Sounwave)")
        assert tag == "V1-V?"
        assert base == "DRONES.(prod. Sounwave)"

    def test_album_tag(self):
        tag, base = extract_version_tag("Man On The Moon [Album](feat. Kanye West)")
        assert tag == "Album"
        assert base == "Man On The Moon(feat. Kanye West)"

    def test_clean_tag(self):
        tag, base = extract_version_tag("RATHER LIE [Clean](ref. Keith Lawson)")
        assert tag == "Clean"
        assert base == "RATHER LIE(ref. Keith Lawson)"

    def test_song_number_tag(self):
        tag, base = extract_version_tag("For Real[Song 2]")
        assert tag == "Song 2"
        assert base == "For Real"

    def test_collaboration_brackets_not_matched(self):
        """[Kanye West Collaborations] is a section label, not a version tag."""
        tag, base = extract_version_tag("Unknown [Kanye West Collaborations]")
        assert tag is None
        assert base == "Unknown [Kanye West Collaborations]"


class TestEraMatchKey:
    def test_strips_parenthetical(self):
        assert _era_match_key("Before Baby Keem(as Hykeem Carter)") == "before baby keem"

    def test_no_parens(self):
        assert _era_match_key("THC: The High Chronical$") == "thc: the high chronical$"

    def test_parens_with_space(self):
        key = _era_match_key("Whole Lotta Red (Deluxe)")
        assert "whole lotta red" in key

    def test_case_insensitive(self):
        assert _era_match_key("Ca$ino(Child With Wolves)") == "ca$ino"

    def test_strips_version_tag(self):
        assert _era_match_key("Tu Pimp A Caterpillar [V1](early version)") == "tu pimp a caterpillar"
        assert _era_match_key("To Pimp A Butterfly [V2](studio)") == "to pimp a butterfly"


# ---------------------------------------------------------------------------
# Column detection tests
# ---------------------------------------------------------------------------

class TestColumnDetection:
    def test_ye_columns(self, ye):
        """Ye tracker should detect 9 standard columns."""
        sheet_path = TRACKERS_DIR / "Ye Tracker - Google Drive_files" / "sheet.html"
        html = sheet_path.read_text(encoding="utf-8")
        rows = extract_table(html)
        col_map = detect_columns(rows[0])
        assert "era" in col_map
        assert "name" in col_map
        assert "notes" in col_map
        assert "track_length" in col_map
        assert "file_date" in col_map
        assert "leak_date" in col_map
        assert "available_length" in col_map
        assert "quality" in col_map
        assert "links" in col_map

    def test_carti_columns(self, carti):
        """Carti tracker should have extra columns for type and date_of_recording."""
        sheet_path = TRACKERS_DIR / "Playboi Carti Tracker [Currently in Use] - Google Drive_files" / "sheet.html"
        html = sheet_path.read_text(encoding="utf-8")
        rows = extract_table(html)
        col_map = detect_columns(rows[0])
        assert "date_of_recording" in col_map
        assert "type" in col_map
        assert "notes" in col_map  # The prefix-match fallback should find "Notes"


# ---------------------------------------------------------------------------
# Structural integrity tests — every tracker
# ---------------------------------------------------------------------------

class TestAllTrackers:
    """Basic structural checks that must hold for all supported trackers."""

    def test_all_four_trackers_discovered(self, all_artists):
        assert len(all_artists) == 4
        assert set(all_artists.keys()) == {"Ye", "Kendrick Lamar", "Baby Keem", "Playboi Carti"}

    def test_every_artist_has_eras(self, all_artists):
        for name, artist in all_artists.items():
            assert len(artist.eras) > 0, f"{name} has no eras"

    def test_every_artist_has_songs(self, all_artists):
        for name, artist in all_artists.items():
            assert artist.total_songs > 0, f"{name} has no songs"

    def test_slug_is_lowercase(self, all_artists):
        for artist in all_artists.values():
            assert artist.slug == artist.slug.lower()
            assert " " not in artist.slug

    def test_no_era_has_negative_songs(self, all_artists):
        for artist in all_artists.values():
            for era in artist.eras:
                assert era.song_count >= 0


# ---------------------------------------------------------------------------
# Ye-specific tests (ground truth from manual inspection)
# ---------------------------------------------------------------------------

class TestYeTracker:
    def test_era_count(self, ye):
        # Ye has ~42 eras
        assert ye.total_songs > 5000
        assert len(ye.eras) >= 40

    def test_yeezus_2_era_exists(self, ye):
        era_names = [e.name for e in ye.eras]
        matching = [n for n in era_names if "Yeezus 2" in n]
        assert len(matching) == 1

    def test_yeezus_2_song_count(self, ye):
        """Yeezus 2 should have ~245 songs based on dump."""
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        assert era.song_count >= 200

    def test_yeezus_2_a_pas_de_velour(self, ye):
        """First song in Yeezus 2 era — from screenshot verification."""
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        # Find 'A Pas de Velour'
        song = next((s for s in era.songs if "A Pas de Velour" in s.base_name), None)
        assert song is not None
        v = song.versions[0]
        assert v.available_length == "Rumored"
        assert v.quality == "Not Available"
        assert v.file_date == "Jan 7, 2014"

    def test_about_time_metadata(self, ye):
        """About Time in Yeezus 2 — verified from screenshot."""
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        song = next((s for s in era.songs if s.base_name == "About Time"), None)
        assert song is not None
        v = song.versions[0]
        assert v.track_length == "0:42"
        assert v.available_length == "OG File"
        assert v.quality == "Lossless"
        assert v.leak_date == "Mar 20, 2023"
        assert v.file_date == "Nov 11, 2013"

    def test_star_badge_parsed(self, ye):
        """⭐ Black Skinhead (Remix) [V3] should have BEST badge."""
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        song = next((s for s in era.songs if "Black Skinhead" in s.base_name and "Remix" in s.base_name), None)
        assert song is not None
        v3_versions = [v for v in song.versions if v.version_tag == "V3"]
        badged = [v for v in v3_versions if v.badge == Badge.BEST]
        assert len(badged) >= 1

    def test_links_extracted(self, ye):
        """Songs should have links extracted."""
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        songs_with_links = [s for s in era.songs for v in s.versions if v.links]
        assert len(songs_with_links) > 100

    def test_donda_era_exists(self, ye):
        era_names_lower = [e.name.lower() for e in ye.eras]
        assert any("donda" in n for n in era_names_lower)


# ---------------------------------------------------------------------------
# Kendrick-specific tests
# ---------------------------------------------------------------------------

class TestKendrickTracker:
    def test_era_count(self, kendrick):
        assert len(kendrick.eras) >= 15

    def test_total_songs(self, kendrick):
        assert kendrick.total_songs >= 500

    def test_tpab_era_exists(self, kendrick):
        """To Pimp a Butterfly should be an era."""
        era_names = [e.name for e in kendrick.eras]
        matching = [n for n in era_names if "Pimp" in n and "Butterfly" in n]
        assert len(matching) >= 1

    def test_section80_era_exists(self, kendrick):
        era_names = [e.name for e in kendrick.eras]
        matching = [n for n in era_names if "Section" in n or "section" in n]
        assert len(matching) >= 1


# ---------------------------------------------------------------------------
# Baby Keem tests
# ---------------------------------------------------------------------------

class TestBabyKeemTracker:
    def test_era_count(self, keem):
        assert len(keem.eras) >= 5

    def test_total_songs(self, keem):
        assert keem.total_songs >= 150

    def test_the_melodic_blue(self, keem):
        era_names = [e.name for e in keem.eras]
        matching = [n for n in era_names if "Melodic Blue" in n]
        assert len(matching) == 1


# ---------------------------------------------------------------------------
# Playboi Carti tests
# ---------------------------------------------------------------------------

class TestCartiTracker:
    def test_era_count(self, carti):
        assert len(carti.eras) >= 10

    def test_total_songs(self, carti):
        assert carti.total_songs >= 400

    def test_carti_specific_fields(self, carti):
        """Carti tracker has 'type' and 'date_of_recording' columns."""
        has_type = False
        has_recording_date = False
        for era in carti.eras:
            for song in era.songs:
                for v in song.versions:
                    if v.type:
                        has_type = True
                    if v.date_of_recording:
                        has_recording_date = True
                    if has_type and has_recording_date:
                        break
        assert has_type, "No Carti song has a 'type' field"
        assert has_recording_date, "No Carti song has a 'date_of_recording' field"

    def test_wlr_era_exists(self, carti):
        era_names = [e.name for e in carti.eras]
        matching = [n for n in era_names if "Whole Lotta Red" in n]
        assert len(matching) >= 1


# ---------------------------------------------------------------------------
# Note-links merge regression tests
# ---------------------------------------------------------------------------

class TestNoteLinksMerge:
    """Ensure links embedded in the notes cell are included in version.links."""

    def test_kendrick_note_only_link(self, kendrick):
        """Hotel Paranoia only has a link in its notes cell (no dedicated links column link).

        Before the fix, this song had zero links. After the fix, the YouTube
        link extracted from the notes cell must be present.
        """
        song = None
        for era in kendrick.eras:
            for s in era.songs:
                if s.base_name == "Hotel Paranoia":
                    song = s
                    break
        assert song is not None, "Hotel Paranoia not found in Kendrick tracker"
        links = song.versions[0].links
        assert len(links) > 0, "Hotel Paranoia should have at least one link (from notes cell)"
        assert any("youtube.com" in lnk for lnk in links), (
            f"Expected a YouTube link in Hotel Paranoia, got: {links}"
        )

    def test_keem_note_link_merged_with_link_col(self, keem):
        """Bad Guy has links in BOTH the links column AND the notes cell.

        Both should appear in version.links after the fix.
        """
        song = None
        for era in keem.eras:
            for s in era.songs:
                if "Bad Guy" in s.base_name:
                    song = s
                    break
        assert song is not None, "Bad Guy not found in Baby Keem tracker"
        links = song.versions[0].links
        assert len(links) >= 2, (
            f"Bad Guy should have at least 2 links (links col + notes col), got: {links}"
        )

    def test_total_links_increased_for_kendrick(self, kendrick):
        """With note-links merged, at least 646 Kendrick versions should have links."""
        total_links = sum(
            len(v.links) for era in kendrick.eras for s in era.songs for v in s.versions
        )
        # 735 total links (646 versions with at least one link) after the fix
        assert total_links >= 735, f"Expected >=735 links, got {total_links}"


# ---------------------------------------------------------------------------
# Version tag grouping regression tests
# ---------------------------------------------------------------------------

class TestVersionTagGrouping:
    """Ensure new version tag patterns group songs correctly."""

    def test_carti_master_grouped_with_v1(self, carti):
        """Location [MASTER] and Location [V1] belong to the same base song."""
        song = None
        for era in carti.eras:
            for s in era.songs:
                if "Location" in s.base_name and "Harry Fraud" in s.base_name:
                    song = s
                    break
        assert song is not None, "Location (Harry Fraud) not found in Carti tracker"
        version_tags = {v.version_tag for v in song.versions}
        assert "V1" in version_tags, f"Expected V1 in {version_tags}"
        assert "MASTER" in version_tags, f"Expected MASTER in {version_tags}"

    def test_carti_cd_version_tag_parsed(self, carti):
        """CD VERSION tag should be recognized and stored as version_tag."""
        has_cd = any(
            v.version_tag and v.version_tag.upper() == "CD VERSION"
            for era in carti.eras
            for s in era.songs
            for v in s.versions
        )
        assert has_cd, "No song with CD VERSION tag found in Carti tracker"

    def test_carti_unknown_version_tag(self, carti):
        """V? tag (unknown version number) should be recognized."""
        has_vq = any(
            v.version_tag == "V?"
            for era in carti.eras
            for s in era.songs
            for v in s.versions
        )
        assert has_vq, "No song with V? tag found in Carti tracker"

    def test_ye_album_tag_parsed(self, ye):
        """[Album] tag on Ye tracker should be recognized as a version tag."""
        has_album = any(
            v.version_tag and v.version_tag.lower() == "album"
            for era in ye.eras
            for s in era.songs
            for v in s.versions
        )
        assert has_album, "No song with Album tag found in Ye tracker"


# ---------------------------------------------------------------------------
# Zero-song era diagnosis (regression tests)
# ---------------------------------------------------------------------------

class TestZeroEraRegression:
    """Ensure known problematic eras have songs (catches matching regressions)."""

    def test_ye_yeezus_eras_have_songs(self, ye):
        for era in ye.eras:
            if "Yeezus" in era.name:
                assert era.song_count > 0, f"Ye era '{era.name}' has 0 songs"

    def test_keem_all_eras_have_songs(self, keem):
        zero_eras = [e for e in keem.eras if e.song_count == 0]
        assert len(zero_eras) == 0, f"Keem eras with 0 songs: {[e.name for e in zero_eras]}"

    def test_kendrick_most_eras_have_songs(self, kendrick):
        """Allow at most 2 eras with 0 songs (known edge cases)."""
        zero_eras = [e for e in kendrick.eras if e.song_count == 0]
        assert len(zero_eras) <= 2, f"Too many 0-song eras: {[e.name for e in zero_eras]}"


# ---------------------------------------------------------------------------
# Fetcher unit tests
# ---------------------------------------------------------------------------

class TestFetcherHelpers:
    """Test fetcher helper functions (no network required)."""

    def test_infer_artist_name(self):
        from src.fetcher import _infer_artist_name
        assert _infer_artist_name("Ye Tracker - Google Drive") == "Ye"
        assert _infer_artist_name("Baby Keem Music Tracker - Google Drive") == "Baby Keem"
        assert _infer_artist_name("Playboi Carti Tracker [Currently in Use] - Google Drive") == "Playboi Carti"
        assert _infer_artist_name("Kendrick Lamar Music Tracker - Google Drive") == "Kendrick Lamar"

    def test_extract_sheet_id(self):
        from src.fetcher import _extract_sheet_id
        url = "https://docs.google.com/spreadsheets/d/1-FxUYaxBqav0G6txAAixy7bhTGs86sItN_0_F8ekeKQ/htmlview"
        assert _extract_sheet_id(url) == "1-FxUYaxBqav0G6txAAixy7bhTGs86sItN_0_F8ekeKQ"

    def test_normalize_url(self):
        from src.fetcher import _normalize_url
        assert _normalize_url("yetracker.net/").startswith("https://")
        assert _normalize_url("https://yetracker.net/") == "https://yetracker.net/"

    def test_build_sheet_html_url_google(self):
        from src.fetcher import _build_sheet_html_url
        url = _build_sheet_html_url(
            "https://docs.google.com/spreadsheets/d/ABC123/htmlview", "0"
        )
        assert "/htmlview/sheet" in url
        assert "gid=0" in url
        assert "headers=true" in url

    def test_build_sheet_html_url_custom(self):
        from src.fetcher import _build_sheet_html_url
        url = _build_sheet_html_url("https://yetracker.net/", "34972268")
        assert "yetracker.net/htmlview/sheet" in url
        assert "gid=34972268" in url
