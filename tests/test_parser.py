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
        assert base == "After You (prod. Dom $olo)"

    def test_master_tag(self):
        tag, base = extract_version_tag("Location [MASTER](prod. Harry Fraud)")
        assert tag == "MASTER"
        assert base == "Location (prod. Harry Fraud)"

    def test_cd_version_tag(self):
        tag, base = extract_version_tag("POP OUT [CD VERSION](prod. F1LTHY)")
        assert tag == "CD VERSION"
        assert base == "POP OUT (prod. F1LTHY)"

    def test_unknown_version_tag(self):
        tag, base = extract_version_tag("Red Lean [V?](feat. Lil Uzi Vert)")
        assert tag == "V?"
        assert base == "Red Lean (feat. Lil Uzi Vert)"

    def test_version_range_unknown_upper(self):
        tag, base = extract_version_tag("DRONES. [V1-V?](prod. Sounwave)")
        assert tag == "V1-V?"
        assert base == "DRONES. (prod. Sounwave)"

    def test_album_tag(self):
        tag, base = extract_version_tag("Man On The Moon [Album](feat. Kanye West)")
        assert tag == "Album"
        assert base == "Man On The Moon (feat. Kanye West)"

    def test_clean_tag(self):
        tag, base = extract_version_tag("RATHER LIE [Clean](ref. Keith Lawson)")
        assert tag == "Clean"
        assert base == "RATHER LIE (ref. Keith Lawson)"

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

    def test_purely_parenthetical(self):
        """Image-based era names may leave only parenthetical alt-names as text."""
        assert _era_match_key("(Mollyworld, Balaclava Era)") == "mollyworld, balaclava era"

    def test_empty_name(self):
        assert _era_match_key("") == ""


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
        # Ye has ~42 eras; total unique songs ~3400+ (songs group by clean base name)
        assert ye.total_songs > 3000
        assert len(ye.eras) >= 40

    def test_yeezus_2_era_exists(self, ye):
        era_names = [e.name for e in ye.eras]
        matching = [n for n in era_names if "Yeezus 2" in n]
        assert len(matching) == 1

    def test_yeezus_2_song_count(self, ye):
        """Yeezus 2 should have ~150 songs (matches era stats OG File count)."""
        era = next(e for e in ye.eras if "Yeezus 2" in e.name)
        assert era.song_count >= 130

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
                if "Location" in s.base_name:
                    # Find the Location produced by Harry Fraud
                    if any(
                        v.producers and "Harry Fraud" in v.producers
                        for v in s.versions
                    ):
                        song = s
                        break
        assert song is not None, "Location (prod. Harry Fraud) not found in Carti tracker"
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


# ---------------------------------------------------------------------------
# Era stats parsing tests
# ---------------------------------------------------------------------------

class TestEraStatsParsing:
    """Test structured parsing of era stats metadata."""

    def test_parse_era_stats_basic(self):
        from src.models import parse_era_stats
        raw = "1 OG File(s)\n45 Full\n1 Tagged\n3 Partial\n4 Snippet(s)\n0 Stem Bounce(s)\n70 Unavailable"
        stats = parse_era_stats(raw)
        assert stats.og_files == 1
        assert stats.full == 45
        assert stats.tagged == 1
        assert stats.partial == 3
        assert stats.snippets == 4
        assert stats.stem_bounces == 0
        assert stats.unavailable == 70
        assert stats.total == 124

    def test_parse_era_stats_concatenated(self):
        """Stats without newlines (old parser behavior before br fix)."""
        from src.models import parse_era_stats
        raw = "1 OG File(s)45 Full1 Tagged3 Partial4 Snippet(s)0 Stem Bounce(s)70 Unavailable"
        stats = parse_era_stats(raw)
        assert stats.og_files == 1
        assert stats.full == 45
        assert stats.total == 124

    def test_parse_era_stats_carti_format(self):
        """Carti trackers use 'Total Full' instead of 'Full'."""
        from src.models import parse_era_stats
        raw = "1 Total Full\n0 OG File\n0 Partial / Cut\n0 Snippet\n3 Unavailable"
        stats = parse_era_stats(raw)
        assert stats.full == 1
        assert stats.unavailable == 3
        assert stats.total == 4

    def test_ye_eras_have_stats(self, ye):
        """All Ye eras should have parsed stats."""
        for era in ye.eras:
            assert era.stats is not None, f"Era '{era.name}' has no parsed stats"
            assert era.stats.total >= 0

    def test_keem_eras_have_stats(self, keem):
        for era in keem.eras:
            assert era.stats is not None, f"Era '{era.name}' has no parsed stats"

    def test_kendrick_eras_have_stats(self, kendrick):
        for era in kendrick.eras:
            if era.stats_raw:  # only eras from stat-based headers
                assert era.stats is not None, f"Era '{era.name}' has no parsed stats"

    def test_carti_eras_have_stats(self, carti):
        for era in carti.eras:
            if era.stats_raw:  # only eras from stat-based headers
                assert era.stats is not None, f"Era '{era.name}' has no parsed stats"

    def test_ye_total_from_era_stats(self, ye):
        """Sum of era stats totals should be close to total_versions."""
        era_sum = sum(e.stats.total for e in ye.eras if e.stats)
        # Allow small discrepancy due to sub-headers and stale metadata
        assert abs(era_sum - ye.total_versions) < 50, (
            f"Era stats sum {era_sum} vs total_versions {ye.total_versions}"
        )


# ---------------------------------------------------------------------------
# Era art tests
# ---------------------------------------------------------------------------

class TestEraArt:
    """Test era cover art extraction."""

    def test_ye_at_least_one_era_has_art(self, ye):
        """At least one Ye era should have art (local files have fewer images than live)."""
        eras_with_art = [e for e in ye.eras if e.art_url]
        assert len(eras_with_art) >= 1, "No Ye era has art_url"

    def test_keem_at_least_one_era_has_art(self, keem):
        eras_with_art = [e for e in keem.eras if e.art_url]
        assert len(eras_with_art) >= 1, "No Keem era has art_url"

    def test_art_url_format(self, ye):
        """Art URLs should be either HTTPS CDN links (live) or relative paths (local)."""
        for era in ye.eras:
            if era.art_url:
                is_live = era.art_url.startswith("https://")
                is_local = era.art_url.startswith("./") or era.art_url.endswith(".jpg")
                assert is_live or is_local, f"Unexpected art_url format: {era.art_url}"


# ---------------------------------------------------------------------------
# Global tracker stats tests
# ---------------------------------------------------------------------------

class TestTrackerStats:
    """Test global tracker statistics parsing."""

    def test_parse_tracker_stats_basic(self):
        from src.models import parse_tracker_stats
        links = "6243 Total Links\n28 Missing Links\n49 Sources Needed\n1023 Not Avaliable"
        quality = "1150 Lossless\n2714 CD Quality\n868 High Quality\n116 Low Quality\n649 Recordings\n2626 Not Available"
        avail = "4146 Total Full\n2973 OG Files\n232 Stem Bounces\n880 Full\n61 Tagged\n332 Partial\n889 Snippets\n2756 Unavailable"
        highlights = "\u2b50 139 Best Of\n\u2728 291 Special\n\U0001f3c6 29 Grails\n\U0001f396 45 Wanted\n\U0001f5d1\ufe0f 69 Worst Of"

        stats = parse_tracker_stats(links, quality, avail, highlights)
        assert stats.total_links == 6243
        assert stats.missing_links == 28
        assert stats.lossless == 1150
        assert stats.cd_quality == 2714
        assert stats.total_full == 4146
        assert stats.og_files == 2973
        assert stats.best_of == 139
        assert stats.special == 291
        assert stats.grails == 29
        assert stats.wanted == 45
        assert stats.worst_of == 69

    def test_parse_tracker_stats_emoji_prefix(self):
        """Kendrick/Keem style: emoji-prefixed stat labels."""
        from src.models import parse_tracker_stats
        links = "\U0001f517 616 Total Links\n\u274c 0 Missing Links\n\U0001f4da 0 Sources Needed\n\U0001f6ab 217 Not Available"
        quality = "\U0001f4bf 53 Lossless\n\U0001f4c0 195 CD Quality\n\U0001f3b5 163 High Quality\n\U0001f4c9 21 Low Quality\n\U0001f399\ufe0f 64 Recordings\n\U0001f6ab 365 Not Available"
        avail = "\U0001f4c1 282 Total Full\n\U0001f9fe 154 OG Files\n\U0001f3bc 119 Full\n\U0001f3f7\ufe0f 9 Tagged\n\U0001f539 39 Partial\n\u2702\ufe0f 124 Snippets"
        highlights = "\u2b50 61 Best Of\n\u2728 97 Special\n\U0001f3c6 51 Grails\n\U0001f5d1\ufe0f 9 Worst Of"

        stats = parse_tracker_stats(links, quality, avail, highlights)
        assert stats.total_links == 616
        assert stats.lossless == 53
        assert stats.cd_quality == 195
        assert stats.total_full == 282
        assert stats.best_of == 61
        assert stats.grails == 51

    def test_ye_has_tracker_stats(self, ye):
        assert ye.tracker_stats is not None
        assert ye.tracker_stats.total_links > 1000

    def test_keem_has_tracker_stats(self, keem):
        assert keem.tracker_stats is not None
        assert keem.tracker_stats.total_links > 100

    def test_kendrick_has_tracker_stats(self, kendrick):
        assert kendrick.tracker_stats is not None
        assert kendrick.tracker_stats.total_links > 100


# ---------------------------------------------------------------------------
# Footer detection regression test
# ---------------------------------------------------------------------------

class TestFooterDetection:
    """Ensure tracker footer rows are not parsed as songs."""

    def test_kendrick_last_era_not_inflated(self, kendrick):
        """The last era should not contain changelog/guideline entries."""
        last_era = kendrick.eras[-1]
        for song in last_era.songs:
            for v in song.versions:
                assert "Tracker Guidelines" not in v.name, (
                    f"Footer text leaked into last era: {v.name}"
                )
                assert "Changelogs" not in v.name
                assert "Editor Comments" not in v.name

    def test_keem_last_era_not_inflated(self, keem):
        last_era = keem.eras[-1]
        for song in last_era.songs:
            for v in song.versions:
                assert "Tracker Guidelines" not in v.name


# ---------------------------------------------------------------------------
# Song credit parsing tests
# ---------------------------------------------------------------------------

class TestSongCreditParsing:
    """Test parse_song_credits extracts features, producers, alt titles."""

    def test_full_credits(self):
        from src.models import parse_song_credits
        raw = "10 in a Benz \n(with Go Getters) (feat. Rhymefest) (prod. Kanye West & Andy C.)\n(On 10 in a Benz)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "10 in a Benz"
        assert feat == "Rhymefest"
        assert prod == "Kanye West & Andy C."
        assert collab == "Go Getters"
        assert refs is None
        assert alts == ["On 10 in a Benz"]

    def test_feat_and_prod_only(self):
        from src.models import parse_song_credits
        raw = "3 Minutes of Watts\n(feat. J-Rock) (prod. Don-P)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "3 Minutes of Watts"
        assert feat == "J-Rock"
        assert prod == "Don-P"
        assert collab is None
        assert alts == []

    def test_prod_on_separate_line(self):
        from src.models import parse_song_credits
        raw = "Living Reckless [V1]\n(prod. Ski Beatz)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "Living Reckless [V1]"
        assert prod == "Ski Beatz"
        assert feat is None

    def test_prod_glued_to_version_tag(self):
        from src.models import parse_song_credits
        raw = "After You [V2](prod. Dom $olo)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "After You [V2]"
        assert prod == "Dom $olo"

    def test_ref_credits(self):
        from src.models import parse_song_credits
        raw = "RATHER LIE [Clean](ref. Keith Lawson)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "RATHER LIE [Clean]"
        assert refs == "Keith Lawson"

    def test_alt_title_only(self):
        from src.models import parse_song_credits
        raw = "On My Own\n(My Own)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "On My Own"
        assert alts == ["My Own"]

    def test_multiple_alt_titles(self):
        from src.models import parse_song_credits
        raw = "I'm Him\n(prod. Hykeem Carter)\n(I'm The Man, Thank God)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "I'm Him"
        assert prod == "Hykeem Carter"
        assert alts == ["I'm The Man, Thank God"]

    def test_no_credits(self):
        from src.models import parse_song_credits
        raw = "Ain't No Money"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "Ain't No Money"
        assert feat is None
        assert prod is None
        assert collab is None
        assert refs is None
        assert alts == []

    def test_remix_stays_in_title(self):
        from src.models import parse_song_credits
        raw = "Black Skinhead (Remix) [V3]"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "Black Skinhead (Remix) [V3]"
        assert feat is None

    def test_complex_featuring(self):
        from src.models import parse_song_credits
        raw = "All I Need \n(with Go Getters) (feat. Kanye West, Mikkey Halsted, Taji & Miss Criss) (prod. AllDay & Kanye West) \n(All I Have)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "All I Need"
        assert "Kanye West" in feat
        assert "Mikkey Halsted" in feat
        assert collab == "Go Getters"
        assert "AllDay" in prod
        assert alts == ["All I Have"]

    def test_artist_prefix_stays_in_title(self):
        from src.models import parse_song_credits
        raw = "Jay Rock - To The Top\n(feat. K-Dot) (prod. DJ Mano)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "Jay Rock - To The Top"
        assert feat == "K-Dot"
        assert prod == "DJ Mano"

    def test_carti_format(self):
        from src.models import parse_song_credits
        raw = "36 Villainz\n(prod. Cold Hart & DJ Anuedy)\n(36IllVillianz)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "36 Villainz"
        assert prod == "Cold Hart & DJ Anuedy"
        assert alts == ["36IllVillianz"]


# ---------------------------------------------------------------------------
# Song credit fields on parsed tracker data
# ---------------------------------------------------------------------------

class TestSongCreditsOnParsedData:
    """Verify credit fields are populated on actual tracker data."""

    def test_ye_songs_have_producers(self, ye):
        """Many Ye songs have (prod. ...) credits."""
        songs_with_prod = sum(
            1 for era in ye.eras for s in era.songs
            for v in s.versions if v.producers
        )
        assert songs_with_prod > 100, f"Expected >100 songs with producers, got {songs_with_prod}"

    def test_ye_songs_have_featuring(self, ye):
        """Many Ye songs have (feat. ...) credits."""
        songs_with_feat = sum(
            1 for era in ye.eras for s in era.songs
            for v in s.versions if v.featuring
        )
        assert songs_with_feat > 50, f"Expected >50 songs with featuring, got {songs_with_feat}"

    def test_ye_10_in_a_benz_credits(self, ye):
        """Verify 10 in a Benz has correct structured credits."""
        era = next(e for e in ye.eras if "Before The College Dropout" in e.name)
        song = next(s for s in era.songs if s.base_name == "10 in a Benz")
        v = song.versions[0]
        assert v.featuring == "Rhymefest"
        assert v.producers == "Kanye West & Andy C."
        assert v.collaboration == "Go Getters"
        assert "10 in a Benz" in v.alt_titles[0]

    def test_kendrick_songs_have_producers(self, kendrick):
        songs_with_prod = sum(
            1 for era in kendrick.eras for s in era.songs
            for v in s.versions if v.producers
        )
        assert songs_with_prod > 50

    def test_carti_songs_have_producers(self, carti):
        songs_with_prod = sum(
            1 for era in carti.eras for s in era.songs
            for v in s.versions if v.producers
        )
        assert songs_with_prod > 100

    def test_song_name_is_clean_title(self, ye):
        """SongVersion.name should be the clean title line, not multi-line blob."""
        era = next(e for e in ye.eras if "Before The College Dropout" in e.name)
        song = next(s for s in era.songs if s.base_name == "10 in a Benz")
        v = song.versions[0]
        assert "\n" not in v.name, f"version.name should not contain newlines: {v.name!r}"
        assert "(prod." not in v.name, "version.name should not contain producer credits"
        assert "(feat." not in v.name, "version.name should not contain featuring credits"

    def test_base_name_clean(self, ye):
        """base_name should be the song title without credits or version tags."""
        era = next(e for e in ye.eras if "Before The College Dropout" in e.name)
        for song in era.songs[:10]:
            assert "(prod." not in song.base_name, f"base_name has producer: {song.base_name}"
            assert "(feat." not in song.base_name, f"base_name has featuring: {song.base_name}"
            assert "\n" not in song.base_name, f"base_name has newline: {song.base_name}"


# ---------------------------------------------------------------------------
# Timeline parsing tests
# ---------------------------------------------------------------------------

class TestTimelineParsing:
    """Test parse_timeline extracts date+event pairs."""

    def test_ye_format(self):
        from src.models import parse_timeline
        text = "(06/08/1977) (Ye is born in Atlanta)\n(08/18/2002) (Kanye announces he signed to Roc-A-Fella)"
        events = parse_timeline(text)
        assert len(events) == 2
        assert events[0].date == "06/08/1977"
        assert events[0].event == "Ye is born in Atlanta"
        assert events[1].date == "08/18/2002"
        assert "Roc-A-Fella" in events[1].event

    def test_keem_format(self):
        from src.models import parse_timeline
        text = '(2016) Baby Keem releases "Come Thru" to soundcloud.\n(August 16, 2018) Hearts & Darts on streaming.'
        events = parse_timeline(text)
        assert len(events) == 2
        assert events[0].date == "2016"
        assert "Come Thru" in events[0].event
        assert events[1].date == "August 16, 2018"

    def test_carti_format(self):
        from src.models import parse_timeline
        text = "(Sept 13th, 1996) Jordan Terrell Carter is born\n(2009) JCee starts making music"
        events = parse_timeline(text)
        assert len(events) == 2
        assert events[0].date == "Sept 13th, 1996"
        assert events[0].event == "Jordan Terrell Carter is born"

    def test_empty_text(self):
        from src.models import parse_timeline
        assert parse_timeline("") == []

    def test_single_event(self):
        from src.models import parse_timeline
        events = parse_timeline("(2024) Album drops")
        assert len(events) == 1
        assert events[0].date == "2024"
        assert events[0].event == "Album drops"


# ---------------------------------------------------------------------------
# Era timeline and description tests
# ---------------------------------------------------------------------------

class TestEraTimelineAndDescription:
    """Verify era headers properly separate timeline from description."""

    def test_ye_first_era_has_timeline(self, ye):
        era = ye.eras[0]
        assert len(era.timeline) >= 2
        assert era.timeline[0].date == "06/08/1977"
        assert "born" in era.timeline[0].event.lower()

    def test_ye_first_era_has_description(self, ye):
        era = ye.eras[0]
        assert era.description is not None
        assert len(era.description) > 100
        assert "Go Getters" in era.description

    def test_ye_description_not_timeline(self, ye):
        """era.description should not contain timeline data."""
        for era in ye.eras:
            if era.description:
                # Description should not start with (date) pattern
                assert not era.description.startswith("("), (
                    f"Era '{era.name}' description looks like timeline: {era.description[:80]}"
                )

    def test_keem_first_era_has_timeline(self, keem):
        era = keem.eras[0]
        assert len(era.timeline) >= 1

    def test_keem_first_era_has_description(self, keem):
        era = keem.eras[0]
        assert era.description is not None
        assert len(era.description) > 50

    def test_kendrick_first_era_has_timeline(self, kendrick):
        # Find first era with stats (skip any auto-created annotation eras)
        era = next((e for e in kendrick.eras if e.stats_raw), kendrick.eras[0])
        assert len(era.timeline) >= 2

    def test_carti_first_era_has_timeline(self, carti):
        era = carti.eras[0]
        assert len(era.timeline) >= 2

    def test_all_eras_timeline_is_list(self, ye, keem, kendrick, carti):
        """Every era should have a timeline list (possibly empty)."""
        for artist in [ye, keem, kendrick, carti]:
            for era in artist.eras:
                assert isinstance(era.timeline, list)


# ---------------------------------------------------------------------------
# Notes-column section label tests
# ---------------------------------------------------------------------------

def test_notes_column_section_label():
    """Section labels in the Notes column (not Name) should be added to current era."""
    from src.parser import parse_file
    from src.config import discover_trackers
    trackers = dict(discover_trackers())
    result = parse_file(str(trackers["Playboi Carti"]), "Playboi Carti")
    # WLR Higher Bitrate Files and Festival Remixes should NOT be in unmatched
    assert result.parse_metadata.skipped_rows == 0, f"Unmatched: {result.parse_metadata.unmatched_rows}"
