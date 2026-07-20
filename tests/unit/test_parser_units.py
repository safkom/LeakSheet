"""Pure-function unit tests for the parser and model helpers.

Extracted from the old monolithic tests/test_parser.py — everything here uses
inline data or public helpers only (no gitignored Trackers/ dumps), so it runs
in the default offline gate. The tracker-integration assertions that need real
dumps live in tests/accuracy/ behind the ``accuracy`` marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import Badge, extract_badge, extract_version_tag
from src.parser import _era_match_key, detect_columns, extract_table, parse_file


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
        assert extract_version_tag("Afta U [V1]") == ("V1", "Afta U")

    def test_v_range(self):
        assert extract_version_tag("Something [V2-V25]") == ("V2-V25", "Something")

    def test_alt_tag(self):
        assert extract_version_tag("Song [Alt.]") == ("Alt.", "Song")

    def test_no_tag(self):
        assert extract_version_tag("About Time") == (None, "About Time")

    def test_tag_with_parens_after(self):
        assert extract_version_tag("After You [V2](prod. Dom $olo)") == ("V2", "After You (prod. Dom $olo)")

    def test_master_tag(self):
        assert extract_version_tag("Location [MASTER](prod. Harry Fraud)") == ("MASTER", "Location (prod. Harry Fraud)")

    def test_cd_version_tag(self):
        assert extract_version_tag("POP OUT [CD VERSION](prod. F1LTHY)") == ("CD VERSION", "POP OUT (prod. F1LTHY)")

    def test_unknown_version_tag(self):
        assert extract_version_tag("Red Lean [V?](feat. Lil Uzi Vert)") == ("V?", "Red Lean (feat. Lil Uzi Vert)")

    def test_version_range_unknown_upper(self):
        assert extract_version_tag("DRONES. [V1-V?](prod. Sounwave)") == ("V1-V?", "DRONES. (prod. Sounwave)")

    def test_album_tag(self):
        assert extract_version_tag("Man On The Moon [Album](feat. Kanye West)") == ("Album", "Man On The Moon (feat. Kanye West)")

    def test_clean_tag(self):
        assert extract_version_tag("RATHER LIE [Clean](ref. Keith Lawson)") == ("Clean", "RATHER LIE (ref. Keith Lawson)")

    def test_song_number_tag(self):
        assert extract_version_tag("For Real[Song 2]") == ("Song 2", "For Real")

    def test_collaboration_brackets_not_matched(self):
        """[Kanye West Collaborations] is a section label, not a version tag."""
        assert extract_version_tag("Unknown [Kanye West Collaborations]") == (
            None, "Unknown [Kanye West Collaborations]"
        )


class TestEraMatchKey:
    def test_strips_parenthetical(self):
        assert _era_match_key("Before Baby Keem(as Hykeem Carter)") == "before baby keem"

    def test_no_parens(self):
        assert _era_match_key("THC: The High Chronical$") == "thc the high chronical$"

    def test_parens_with_space(self):
        assert "whole lotta red" in _era_match_key("Whole Lotta Red (Deluxe)")

    def test_case_insensitive(self):
        assert _era_match_key("Ca$ino(Child With Wolves)") == "ca$ino"

    def test_strips_version_tag(self):
        assert _era_match_key("Tu Pimp A Caterpillar [V1](early version)") == "tu pimp a caterpillar"
        assert _era_match_key("To Pimp A Butterfly [V2](studio)") == "to pimp a butterfly"

    def test_purely_parenthetical(self):
        assert _era_match_key("(Mollyworld, Balaclava Era)") == "mollyworld balaclava era"

    def test_empty_name(self):
        assert _era_match_key("") == ""


class TestFetcherHelpers:
    """Fetcher helper functions (no network required)."""

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


class TestEraStatsParsing:
    """Structured parsing of era stats metadata (pure — no fixtures)."""

    def test_parse_era_stats_basic(self):
        from src.models import parse_era_stats
        raw = "1 OG File(s)\n45 Full\n1 Tagged\n3 Partial\n4 Snippet(s)\n0 Stem Bounce(s)\n70 Unavailable"
        stats = parse_era_stats(raw)
        assert (stats.og_files, stats.full, stats.tagged, stats.partial) == (1, 45, 1, 3)
        assert (stats.snippets, stats.stem_bounces, stats.unavailable) == (4, 0, 70)
        assert stats.total == 124

    def test_parse_era_stats_concatenated(self):
        from src.models import parse_era_stats
        raw = "1 OG File(s)45 Full1 Tagged3 Partial4 Snippet(s)0 Stem Bounce(s)70 Unavailable"
        stats = parse_era_stats(raw)
        assert stats.og_files == 1 and stats.full == 45 and stats.total == 124

    def test_parse_era_stats_carti_format(self):
        from src.models import parse_era_stats
        raw = "1 Total Full\n0 OG File\n0 Partial / Cut\n0 Snippet\n3 Unavailable"
        stats = parse_era_stats(raw)
        assert stats.full == 1 and stats.unavailable == 3 and stats.total == 4


class TestTrackerStatsParsing:
    """Global tracker-stats parsing (pure — no fixtures)."""

    def test_parse_tracker_stats_basic(self):
        from src.models import parse_tracker_stats
        links = "6243 Total Links\n28 Missing Links\n49 Sources Needed\n1023 Not Avaliable"
        quality = "1150 Lossless\n2714 CD Quality\n868 High Quality\n116 Low Quality\n649 Recordings\n2626 Not Available"
        avail = "4146 Total Full\n2973 OG Files\n232 Stem Bounces\n880 Full\n61 Tagged\n332 Partial\n889 Snippets\n2756 Unavailable"
        highlights = "⭐ 139 Best Of\n✨ 291 Special\n\U0001f3c6 29 Grails\n\U0001f396 45 Wanted\n\U0001f5d1️ 69 Worst Of"
        stats = parse_tracker_stats(links, quality, avail, highlights)
        assert stats.total_links == 6243 and stats.missing_links == 28
        assert stats.lossless == 1150 and stats.cd_quality == 2714
        assert stats.total_full == 4146 and stats.og_files == 2973
        assert (stats.best_of, stats.special, stats.grails, stats.wanted, stats.worst_of) == (139, 291, 29, 45, 69)

    def test_parse_tracker_stats_emoji_prefix(self):
        from src.models import parse_tracker_stats
        links = "\U0001f517 616 Total Links\n❌ 0 Missing Links\n\U0001f4da 0 Sources Needed\n\U0001f6ab 217 Not Available"
        quality = "\U0001f4bf 53 Lossless\n\U0001f4c0 195 CD Quality\n\U0001f3b5 163 High Quality\n\U0001f4c9 21 Low Quality\n\U0001f399️ 64 Recordings\n\U0001f6ab 365 Not Available"
        avail = "\U0001f4c1 282 Total Full\n\U0001f9fe 154 OG Files\n\U0001f3bc 119 Full\n\U0001f3f7️ 9 Tagged\n\U0001f539 39 Partial\n✂️ 124 Snippets"
        highlights = "⭐ 61 Best Of\n✨ 97 Special\n\U0001f3c6 51 Grails\n\U0001f5d1️ 9 Worst Of"
        stats = parse_tracker_stats(links, quality, avail, highlights)
        assert stats.total_links == 616 and stats.lossless == 53
        assert stats.cd_quality == 195 and stats.total_full == 282
        assert stats.best_of == 61 and stats.grails == 51


class TestStatPairExtraction:
    def test_label_with_trailing_comment(self):
        from src.models import _extract_stat_pairs
        assert _extract_stat_pairs("5 Snippet(s) - new finds") == {"snippet": 5}

    def test_label_with_trailing_punctuation(self):
        from src.models import _extract_stat_pairs
        assert _extract_stat_pairs("45 Full!") == {"full": 45}

    def test_concatenated_format_unchanged(self):
        from src.models import _extract_stat_pairs
        assert _extract_stat_pairs("1 OG File(s)45 Full1 Tagged") == {"og file": 1, "full": 45, "tagged": 1}

    def test_newline_format_unchanged(self):
        from src.models import _extract_stat_pairs
        assert _extract_stat_pairs("1 Total Full\n0 OG File\n3 Unavailable") == {
            "total full": 1, "og file": 0, "unavailable": 3,
        }

    def test_unbalanced_paren_normalizes(self):
        from src.models import _extract_stat_pairs
        assert _extract_stat_pairs("1 OG File(s")["og file"] == 1


class TestSongCreditParsing:
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
        title, feat, prod, collab, refs, alts = parse_song_credits("3 Minutes of Watts\n(feat. J-Rock) (prod. Don-P)")
        assert title == "3 Minutes of Watts"
        assert feat == "J-Rock" and prod == "Don-P" and collab is None and alts == []

    def test_prod_on_separate_line(self):
        from src.models import parse_song_credits
        title, feat, prod, *_ = parse_song_credits("Living Reckless [V1]\n(prod. Ski Beatz)")
        assert title == "Living Reckless [V1]" and prod == "Ski Beatz" and feat is None

    def test_prod_glued_to_version_tag(self):
        from src.models import parse_song_credits
        title, feat, prod, *_ = parse_song_credits("After You [V2](prod. Dom $olo)")
        assert title == "After You [V2]" and prod == "Dom $olo"

    def test_ref_credits(self):
        from src.models import parse_song_credits
        title, feat, prod, collab, refs, alts = parse_song_credits("RATHER LIE [Clean](ref. Keith Lawson)")
        assert title == "RATHER LIE [Clean]" and refs == "Keith Lawson"

    def test_alt_title_only(self):
        from src.models import parse_song_credits
        title, *_, alts = parse_song_credits("On My Own\n(My Own)")
        assert title == "On My Own" and alts == ["My Own"]

    def test_multiple_alt_titles(self):
        from src.models import parse_song_credits
        title, feat, prod, collab, refs, alts = parse_song_credits("I'm Him\n(prod. Hykeem Carter)\n(I'm The Man, Thank God)")
        # 2026-07-17 (PR #10): comma-separated parenthetical aliases split into
        # individual alt titles — see TestCommaAltTitles for the stay-whole guards.
        assert title == "I'm Him" and prod == "Hykeem Carter" and alts == ["I'm The Man", "Thank God"]

    def test_no_credits(self):
        from src.models import parse_song_credits
        title, feat, prod, collab, refs, alts = parse_song_credits("Ain't No Money")
        assert title == "Ain't No Money"
        assert (feat, prod, collab, refs, alts) == (None, None, None, None, [])

    def test_remix_stays_in_title(self):
        from src.models import parse_song_credits
        title, feat, *_ = parse_song_credits("Black Skinhead (Remix) [V3]")
        assert title == "Black Skinhead (Remix) [V3]" and feat is None

    def test_complex_featuring(self):
        from src.models import parse_song_credits
        raw = "All I Need \n(with Go Getters) (feat. Kanye West, Mikkey Halsted, Taji & Miss Criss) (prod. AllDay & Kanye West) \n(All I Have)"
        title, feat, prod, collab, refs, alts = parse_song_credits(raw)
        assert title == "All I Need"
        assert "Kanye West" in feat and "Mikkey Halsted" in feat
        assert collab == "Go Getters" and "AllDay" in prod and alts == ["All I Have"]

    def test_artist_prefix_stays_in_title(self):
        from src.models import parse_song_credits
        title, feat, prod, *_ = parse_song_credits("Jay Rock - To The Top\n(feat. K-Dot) (prod. DJ Mano)")
        assert title == "Jay Rock - To The Top" and feat == "K-Dot" and prod == "DJ Mano"

    def test_carti_format(self):
        from src.models import parse_song_credits
        title, feat, prod, collab, refs, alts = parse_song_credits("36 Villainz\n(prod. Cold Hart & DJ Anuedy)\n(36IllVillianz)")
        assert title == "36 Villainz" and prod == "Cold Hart & DJ Anuedy" and alts == ["36IllVillianz"]


class TestTimelineParsing:
    def test_ye_format(self):
        from src.models import parse_timeline
        events = parse_timeline("(06/08/1977) (Ye is born in Atlanta)\n(08/18/2002) (Kanye announces he signed to Roc-A-Fella)")
        assert len(events) == 2
        assert events[0].date == "06/08/1977" and events[0].event == "Ye is born in Atlanta"
        assert "Roc-A-Fella" in events[1].event

    def test_keem_format(self):
        from src.models import parse_timeline
        events = parse_timeline('(2016) Baby Keem releases "Come Thru" to soundcloud.\n(August 16, 2018) Hearts & Darts on streaming.')
        assert len(events) == 2 and events[0].date == "2016" and "Come Thru" in events[0].event

    def test_carti_format(self):
        from src.models import parse_timeline
        events = parse_timeline("(Sept 13th, 1996) Jordan Terrell Carter is born\n(2009) JCee starts making music")
        assert len(events) == 2 and events[0].date == "Sept 13th, 1996"

    def test_empty_text(self):
        from src.models import parse_timeline
        assert parse_timeline("") == []

    def test_single_event(self):
        from src.models import parse_timeline
        events = parse_timeline("(2024) Album drops")
        assert len(events) == 1 and events[0].date == "2024" and events[0].event == "Album drops"


class TestSampleExtraction:
    def test_pattern2_requires_apostrophe_s(self):
        from src.models import extract_samples
        result = extract_samples('Samples the songs "The Infamous Prelude" by Mobb Deep and "Melodies of Love" by Joe Sample.')
        assert 'The Infamous Prelude — Mobb Deep' in result

    def test_artist_not_truncated_by_vs(self):
        from src.models import extract_samples
        result = extract_samples('Samples "The World is a Ghetto" by George Benson and the Common vs. Kanye freestyle battle.')
        assert result == ['The World is a Ghetto — George Benson']

    def test_multiple_and_separated(self):
        from src.models import extract_samples
        result = extract_samples('Samples the songs "The Infamous Prelude" by Mobb Deep and "Melodies of Love" by Joe Sample.')
        assert result == ['The Infamous Prelude — Mobb Deep', 'Melodies of Love — Joe Sample']

    def test_multiple_comma_separated(self):
        from src.models import extract_samples
        result = extract_samples('Samples "Got Money" by Lil Wayne, "Ain\'t Nobody" by Chaka Khan.')
        assert result == ['Got Money — Lil Wayne', "Ain't Nobody — Chaka Khan"]

    def test_smart_quotes_normalized(self):
        from src.models import extract_samples
        assert extract_samples('Samples “Got Money” by Lil Wayne.') == ['Got Money — Lil Wayne']

    def test_no_stray_quote_characters(self):
        from src.models import extract_samples
        for s in extract_samples('Samples "Got Money" by Lil Wayne. Also samples “Flashing Lights”.'):
            assert '"' not in s and '“' not in s and '”' not in s

    def test_compound_artist_preserved(self):
        from src.models import extract_samples
        assert extract_samples('Samples "Ain\'t Nobody" by Rufus & Chaka Khan.') == ["Ain't Nobody — Rufus & Chaka Khan"]

    def test_pattern2_apostrophe_title(self):
        from src.models import extract_samples
        assert extract_samples("Samples Rufus & Chaka Khan's 'Ain't Nobody'") == ["Ain't Nobody — Rufus & Chaka Khan"]

    def test_artist_prose_not_captured(self):
        from src.models import extract_samples
        result = extract_samples('Samples "Ain\'t Nobody" by Rufus & Chaka Khan. Leaked in Oct 2016 by garetare from the tape.')
        assert result == ["Ain't Nobody — Rufus & Chaka Khan"]

    def test_artist_abbreviation_survives(self):
        from src.models import extract_samples
        assert extract_samples('Samples "Xxplosive" by Dr. Dre') == ["Xxplosive — Dr. Dre"]


class TestOgFilenameExtraction:
    def test_multiple(self):
        from src.models import extract_og_filenames
        notes = "OG Filename: Version A\nSome note\nOG Filename (Metadata): Version B"
        assert extract_og_filenames(notes) == ["Version A", "Version B"]

    def test_single_backcompat(self):
        from src.models import extract_og_filename, extract_og_filenames
        notes = "OG Filename: Broke My Heart 1\nRest of note"
        assert extract_og_filename(notes) == "Broke My Heart 1"
        assert extract_og_filenames(notes) == ["Broke My Heart 1"]

    def test_lines_stripped_from_notes(self):
        from src.models import strip_og_filename_lines
        notes = "OG Filename: Version A\nTrack 12 off the demo tape.\nOG Filename: Version B"
        cleaned = strip_og_filename_lines(notes)
        assert "OG Filename" not in cleaned and cleaned == "Track 12 off the demo tape."

    def test_strip_preserves_notes_without_og(self):
        from src.models import strip_og_filename_lines
        notes = "Track 12 off the demo tape.\nWould later be reused."
        assert strip_og_filename_lines(notes) == notes

    def test_plural_label_with_continuation(self):
        from src.models import extract_og_filenames, strip_og_filename_lines
        notes = "OG Filenames: Ohh Yeah Tellem RUFF &\nOhh Yeah Tellem RUFF 73.3\nInstrumental found in 2020."
        assert extract_og_filenames(notes) == ["Ohh Yeah Tellem RUFF", "Ohh Yeah Tellem RUFF 73.3"]
        assert strip_og_filename_lines(notes) == "Instrumental found in 2020."

    def test_ampersand_before_second_label(self):
        from src.models import extract_og_filenames
        notes = "OG Filename: Paid M17 K 120MT &\nOG Filename: PAID M17 K Master USE Flatten 120MT"
        assert extract_og_filenames(notes) == ["Paid M17 K 120MT", "PAID M17 K Master USE Flatten 120MT"]

    def test_parenthetical_variants(self):
        from src.models import extract_og_filenames
        assert extract_og_filenames("OG Filename (?): Blazin' (KW Verse)") == ["Blazin' (KW Verse)"]
        assert extract_og_filenames("OG Filename (Metadata): Broke My Heart 1") == ["Broke My Heart 1"]

    def test_quoted_midsentence(self):
        from src.models import extract_og_filenames, strip_og_filename_lines
        notes = 'The file included it\'s OG Filename: "KING OF HEARTS MD MIX 2.mp3". This suggests earlier mixes.'
        assert extract_og_filenames(notes) == ["KING OF HEARTS MD MIX 2.mp3"]
        assert strip_og_filename_lines(notes) == notes


class TestLinkCleaning:
    def test_unwraps_google_redirect(self):
        from src.parser import _clean_link
        assert _clean_link("https://www.google.com/url?q=https%3A%2F%2Fpillows.su%2Ff%2Fabc&sa=D") == "https://pillows.su/f/abc"

    def test_wrapper_without_q_returns_original(self):
        from src.parser import _clean_link
        url = "https://www.google.com/url?x=y&z=1"
        assert _clean_link(url) == url

    def test_wrapper_with_empty_q_returns_original(self):
        from src.parser import _clean_link
        url = "https://www.google.com/url?q=&sa=D"
        assert _clean_link(url) == url

    def test_plain_url_untouched(self):
        from src.parser import _clean_link
        assert _clean_link("https://pillows.su/f/abc") == "https://pillows.su/f/abc"

    def test_malformed_url_does_not_raise(self):
        from src.parser import _clean_link
        assert _clean_link("https://www.google.com/url?q=x#[invalid")


class TestSlashEraRegistration:
    @staticmethod
    def _register(era_name, primary, fallback):
        from src.models import Era, Section
        from src.parser import _register_era_keys
        era = Era(name=era_name, sections=[Section()])
        _register_era_keys(era, era_name, primary, fallback)
        return era

    def test_slash_part_goes_to_fallback_not_primary(self):
        primary, fallback = {}, {}
        slash = self._register("38 Baby / Ay Ay", primary, fallback)
        assert primary.get("38 baby / ay ay") is slash
        assert "38 baby" in fallback and primary.get("38 baby") is None
        assert "ay ay" in fallback and primary.get("ay ay") is None

    def test_genuine_era_wins_over_slash_part_registered_first(self):
        primary, fallback = {}, {}
        slash = self._register("38 Baby / Ay Ay", primary, fallback)
        genuine = self._register("Ay Ay", primary, fallback)
        assert primary.get("ay ay") is genuine
        assert fallback.get("ay ay") is slash

    def test_slash_part_resolves_when_no_genuine_era_exists(self):
        primary, fallback = {}, {}
        slash = self._register("38 Baby / Ay Ay", primary, fallback)
        assert primary.get("ay ay") is None
        assert fallback.get("ay ay") is slash and fallback.get("38 baby") is slash

    def test_legacy_call_without_fallback_dict_keeps_old_behaviour(self):
        from src.models import Era, Section
        from src.parser import _register_era_keys
        primary = {}
        era = Era(name="A / B", sections=[Section()])
        _register_era_keys(era, era.name, primary)
        assert primary.get("a") is era and primary.get("b") is era


class TestCommaAltNameRegistration:
    """Comma-separated aliases inside one parenthetical alt line must register
    as individual fallback keys (ported from PR #10).

    Era headers like "Narcissist\\n(Mollyworld, Balaclava Era)" keep the whole
    parenthetical as ONE alt name, so only the composite key is registered. A
    song row referencing a single alias ("Mollyworld") then misses every lookup
    tier and gets positionally mis-assigned. Parts must resolve via the fallback
    dict — never the primary map, so a genuine standalone era keeps priority.
    """

    @staticmethod
    def _register(era_name, alt_names, primary, fallback):
        from src.models import Era, Section
        from src.parser import _register_era_keys
        era = Era(name=era_name, alt_names=alt_names, sections=[Section()])
        _register_era_keys(era, era_name, primary, fallback)
        return era

    def test_comma_alt_parts_go_to_fallback_not_primary(self):
        primary, fallback = {}, {}
        era = self._register("Narcissist", ["Mollyworld, Balaclava Era"], primary, fallback)
        assert primary.get("mollyworld balaclava era") is era
        assert fallback.get("mollyworld") is era
        assert fallback.get("balaclava era") is era
        assert primary.get("mollyworld") is None
        assert primary.get("balaclava era") is None

    def test_genuine_era_wins_over_comma_part(self):
        primary, fallback = {}, {}
        era_a = self._register("Narcissist", ["Mollyworld, Whole Lotta Red"], primary, fallback)
        era_b = self._register("Whole Lotta Red", [], primary, fallback)
        assert primary.get("whole lotta red") is era_b
        assert fallback.get("whole lotta red") is era_a

    def test_volume_continuation_not_split(self):
        primary, fallback = {}, {}
        self._register("Faith", ["Meet The Woo, Vol. 2"], primary, fallback)
        assert "vol 2" not in fallback
        assert "meet the woo" not in fallback

    def test_numeric_comma_not_split(self):
        primary, fallback = {}, {}
        self._register("Era", ["10,000 Days"], primary, fallback)
        assert "000 days" not in fallback

    def test_numeric_alias_in_mixed_list_splits(self):
        """Real Carti case: WE DON'T DIAL 911 declares "14*29, 1429, Trippie
        Redd EP" — numeric aliases are genuine and must register, as long as
        the list has at least one lettered alias."""
        primary, fallback = {}, {}
        era = self._register(
            "WE DON'T DIAL 911", ["14*29, 1429, Trippie Redd EP"], primary, fallback
        )
        assert fallback.get("1429") is era
        assert fallback.get("trippie redd ep") is era
        assert fallback.get("14*29") is era

    def test_single_alias_row_routes_to_declaring_era(self):
        """End-to-end: a row referencing one alias of a comma list lands in
        the era that declared the alias, not the positional current era."""
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>2 Full</td><td>Narcissist<br>(Mollyworld, Balaclava Era)</td><td></td><td></td></tr>"
            "<tr><td>1 Full</td><td>Other Era</td><td></td><td></td></tr>"
            "<tr><td>Mollyworld</td><td>Test Song</td><td>note</td>"
            "<td><a href='https://pillows.su/f/x'>l</a></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        narcissist = next(e for e in artist.eras if e.name == "Narcissist")
        other = next(e for e in artist.eras if e.name == "Other Era")
        assert [s.base_name for s in narcissist.songs] == ["Test Song"]
        assert other.songs == []


class TestCommaAltTitles:
    """Song-level alt-title lines with comma-separated aliases must split
    (ported from PR #10)."""

    def test_comma_separated_alt_titles_split(self):
        from src.models import parse_song_credits
        _, _, _, _, _, alts = parse_song_credits("???\n(Time2Time, Bon Iver Demo)")
        assert alts == ["Time2Time", "Bon Iver Demo"]

    def test_volume_continuation_kept_whole(self):
        from src.models import parse_song_credits
        _, _, _, _, _, alts = parse_song_credits("Some Song\n(Meet The Woo, Vol. 2)")
        assert alts == ["Meet The Woo, Vol. 2"]

    def test_numeric_comma_kept_whole(self):
        from src.models import parse_song_credits
        _, _, _, _, _, alts = parse_song_credits("Some Song\n(10,000 Days)")
        assert alts == ["10,000 Days"]

    def test_roman_numeral_continuation_kept_whole(self):
        from src.models import parse_song_credits
        _, _, _, _, _, alts = parse_song_credits("Song\n(Hell Of A Life, Pt. II)")
        assert alts == ["Hell Of A Life, Pt. II"]

    def test_worded_ordinal_continuation_kept_whole(self):
        from src.models import parse_song_credits
        _, _, _, _, _, alts = parse_song_credits("Song\n(The Story, Part Two)")
        assert alts == ["The Story, Part Two"]

    def test_feat_credit_commas_unaffected(self):
        from src.models import parse_song_credits
        _, feat, _, _, _, alts = parse_song_credits("Some Song\n(feat. Rhymefest, Kanye West)")
        assert feat == "Rhymefest, Kanye West"
        assert alts == []


class TestSongKey:
    """Songs carry a stable normalized song_key for cross-era linkage
    (ported from PR #10)."""

    def test_song_match_key_normalizes(self):
        from src.parser import _song_match_key
        assert _song_match_key("Café Flow!") == "cafe flow"
        assert _song_match_key("THIS ONE HERE") == _song_match_key("This One Here")
        assert _song_match_key("Meet The Woo, Vol. 2") == "meet the woo vol 2"

    def test_songs_share_key_across_eras(self):
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>2 Full</td><td>Donda 2</td><td></td><td></td></tr>"
            "<tr><td>Donda 2</td><td>This One Here</td><td>note</td><td></td></tr>"
            "<tr><td>1 Full</td><td>Bully</td><td></td><td></td></tr>"
            "<tr><td>Bully</td><td>THIS ONE HERE</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        keys = [s.song_key for e in artist.eras for s in e.songs]
        assert len(keys) == 2
        assert keys[0] == keys[1] == "this one here"

    def test_placeholder_with_alt_uses_alt_as_key(self):
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Donda 2</td><td></td><td></td></tr>"
            "<tr><td>Donda 2</td><td>???<br>(Time2Time)</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        assert artist.eras[0].songs[0].song_key == "time2time"

    def test_placeholder_without_alt_has_no_key(self):
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Donda 2</td><td></td><td></td></tr>"
            "<tr><td>Donda 2</td><td>???</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        assert artist.eras[0].songs[0].song_key == ""

    def test_song_key_serialized_in_dict(self):
        from src.models import Song, SongVersion
        song = Song(base_name="Test", song_key="test", versions=[SongVersion(name="Test")])
        assert song.dict()["song_key"] == "test"


class TestPositionalFuzzyPrior:
    """A row-era abbreviation that fuzzy-matches its OWN header must never be
    stolen by a higher-scoring sibling era (2026-07-20 review, 50 Cent).

    Real case: the "Get Rich Or Die Tryin' Soundtrack" header's song rows use
    era="Get Rich Or Die Tryin' OST". Global fuzzy scored the main "Get Rich
    Or Die Tryin'" era 1.0 (4/4 words) vs the Soundtrack era's 0.8 (4/5), so
    all OST songs were misattributed and the Soundtrack era starved (stats
    claim songs, 0 parsed).
    """

    HTML = (
        "<table>"
        "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
        "<tr><td>2 Full</td><td>Get Rich Or Die Tryin'</td><td></td><td></td></tr>"
        "<tr><td>Get Rich Or Die Tryin'</td><td>In Da Club</td><td>note</td><td></td></tr>"
        "<tr><td>1 Full</td><td>Get Rich Or Die Tryin' Soundtrack</td><td></td><td></td></tr>"
        "<tr><td>Get Rich Or Die Tryin' OST</td><td>Pearly Gates</td><td>note</td><td></td></tr>"
        "<tr><td>Get Rich Or Die Tryin' OST</td><td>Gangsta Shit</td><td>note</td><td></td></tr>"
        "</table>"
    )

    def test_abbreviation_stays_with_current_header(self):
        from src.parser import parse_sheet
        artist = parse_sheet(self.HTML, "Test")
        by_name = {e.name: [s.base_name for s in e.songs] for e in artist.eras}
        assert by_name["Get Rich Or Die Tryin'"] == ["In Da Club"]
        assert by_name["Get Rich Or Die Tryin' Soundtrack"] == ["Pearly Gates", "Gangsta Shit"]

    def test_first_row_fuzzy_then_exact_via_fallback(self):
        # Only the FIRST abbreviated row needs fuzzy — the positional match
        # registers the abbreviation in the fallback dict, so subsequent rows
        # resolve exactly.
        from src.parser import parse_sheet
        artist = parse_sheet(self.HTML, "Test")
        assert artist.parse_metadata.fuzzy_matched_rows == 1

    def test_global_fuzzy_still_works_without_positional_context(self):
        """A row far from its era (different current era, no positional link)
        still resolves via the global fuzzy search."""
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Collaboration with Digital Nas</td><td></td><td></td></tr>"
            "<tr><td>1 Full</td><td>Some Other Era</td><td></td><td></td></tr>"
            "<tr><td>Digital Nas Collab</td><td>Lost Song</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        collab = next(e for e in artist.eras if e.name == "Collaboration with Digital Nas")
        assert [s.base_name for s in collab.songs] == ["Lost Song"]


class TestSiblingEraKeyCollision:
    """Version-tagged / slash-named sibling eras share a stripped key; bare
    rows under each header must stay with THEIR header, not the first sibling
    that registered the key (2026-07-20 review: Glocky, NBA Youngboy — every
    later sibling era starved while the first collected all their songs)."""

    def test_version_tagged_siblings_keep_their_rows(self):
        # Glocky class: "Fre3$tyle [V2]" and "[V3]" eras both strip to
        # "fre3$tyle"; rows under [V3] carry the bare name.
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Fre3$tyle [V2]</td><td></td><td></td></tr>"
            "<tr><td>Fre3$tyle</td><td>Song A</td><td>note</td><td></td></tr>"
            "<tr><td>1 Full</td><td>Fre3$tyle [V3]</td><td></td><td></td></tr>"
            "<tr><td>Fre3$tyle</td><td>Song B</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        by_name = {e.name: [s.base_name for s in e.songs] for e in artist.eras}
        assert by_name["Fre3$tyle [V2]"] == ["Song A"]
        assert by_name["Fre3$tyle [V3]"] == ["Song B"]

    def test_slash_named_siblings_keep_their_rows(self):
        # NBA Youngboy class: several headers alias "38 Baby 2" via slash
        # parts; bare rows under each must not all route to the first.
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>38 Baby 2 [V1] / Ain't Too Long</td><td></td><td></td></tr>"
            "<tr><td>38 Baby 2</td><td>No Talkin</td><td>note</td><td></td></tr>"
            "<tr><td>1 Full</td><td>38 Baby 2 [V3] / Post</td><td></td><td></td></tr>"
            "<tr><td>38 Baby 2</td><td>Pain Reliever</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        by_name = {e.name: [s.base_name for s in e.songs] for e in artist.eras}
        assert by_name["38 Baby 2 [V1] / Ain't Too Long"] == ["No Talkin"]
        assert by_name["38 Baby 2 [V3] / Post"] == ["Pain Reliever"]

    def test_rows_far_from_their_era_still_resolve_globally(self):
        # A bare row NOT under any related header keeps the registration-order
        # behavior (first sibling owns the key).
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Fre3$tyle [V2]</td><td></td><td></td></tr>"
            "<tr><td>Fre3$tyle</td><td>Song A</td><td>note</td><td></td></tr>"
            "<tr><td>1 Full</td><td>Unrelated Era</td><td></td><td></td></tr>"
            "<tr><td>Fre3$tyle</td><td>Song C</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        by_name = {e.name: [s.base_name for s in e.songs] for e in artist.eras}
        assert by_name["Fre3$tyle [V2]"] == ["Song A", "Song C"]


class TestStatsHeaderBeatsSeparator:
    """A row carrying era stats in col 0 is an era header even when its name
    matches a section-separator keyword (2026-07-20 review).

    Before the fix, a sparse (2-cell) header like stats + 'Collaboration with
    Digital Nas' was classified as a section separator — the check ran before
    the era-header check — so the era was never created and its song rows had
    nowhere correct to go."""

    def test_sparse_collab_header_creates_era(self):
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Collaboration with Digital Nas</td><td></td><td></td></tr>"
            "<tr><td>Collaboration with Digital Nas</td><td>Team Song</td><td>note</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        collab = next((e for e in artist.eras if e.name == "Collaboration with Digital Nas"), None)
        assert collab is not None, f"eras: {[e.name for e in artist.eras]}"
        assert [s.base_name for s in collab.songs] == ["Team Song"]


class TestNoSilentRowLossOnAutoCreate:
    """Auto-creating an era from a song row must keep the row's song
    (2026-07-20 review).

    The current-era branch created the new era but dropped the parsed
    version on the floor when the row had only a name + notes (no links or
    quality/date metadata) — silent data loss, not even counted as skipped.
    The no-current-era branch already kept the song; the two must agree."""

    def test_notes_only_song_survives_era_autocreate(self):
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Era One</td><td></td><td></td></tr>"
            "<tr><td>Era One</td><td>First Song</td><td>note</td><td></td></tr>"
            "<tr><td>Brand New Chapter</td><td>Some Song</td><td>rumoured to exist</td><td></td></tr>"
            "</table>"
        )
        artist = parse_sheet(html, "Test")
        by_name = {e.name: [s.base_name for s in e.songs] for e in artist.eras}
        assert by_name.get("Brand New Chapter") == ["Some Song"], by_name
        assert artist.parse_metadata.song_rows == 2


class TestFuzzyEraMatch:
    def _eras(self, *names):
        from src.models import Era
        from src.parser import _era_match_key
        return {_era_match_key(n): Era(name=n) for n in names}

    def test_collab_variant_matches(self):
        from src.parser import _fuzzy_era_match
        eras = self._eras("Collaboration with Digital Nas")
        match = _fuzzy_era_match("digital nas collab", eras)
        assert match is not None and match.name == "Collaboration with Digital Nas"

    def test_single_shared_word_does_not_match(self):
        from src.parser import _fuzzy_era_match
        assert _fuzzy_era_match("rodeo days tour", self._eras("Rodeo")) is None

    def test_no_significant_words_no_match(self):
        from src.parser import _fuzzy_era_match
        assert _fuzzy_era_match("ye", self._eras("Ye")) is None


class TestSectionLabelDetection:
    def _row(self, texts):
        from src.parser import _Cell
        return [_Cell(text=t) for t in texts]

    def test_sparse_song_with_notes_is_not_section_label(self):
        from src.models import SongVersion
        from src.parser import _is_section_label_version
        v = SongVersion(name="Throwaway Song", notes="Rumoured to exist from the 2019 sessions.")
        row = self._row(["Some Era", "Throwaway Song", "Rumoured to exist from the 2019 sessions."])
        assert not _is_section_label_version(v, row, era_col=0)

    def test_bare_label_is_section_label(self):
        from src.models import SongVersion
        from src.parser import _is_section_label_version
        v = SongVersion(name="Pre-VMA")
        assert _is_section_label_version(v, self._row(["Some Era", "Pre-VMA", ""]), era_col=0)

    def test_dynamic_label_rejects_linked_rows(self):
        from src.parser import _Cell, _is_dynamic_section_label
        row = [_Cell(text=""), _Cell(text="WLR Higher Bitrate Files", links=["https://x.test/f"]), _Cell(text="")]
        assert _is_dynamic_section_label(row, {"name": 1}) is None


class TestExtractTable:
    def test_html_entities_decoded(self):
        rows = extract_table(
            "<table><tr><td>Era</td><td>Name</td></tr>"
            "<tr><td>Caf&eacute; Era</td><td>Song &amp; Co</td></tr></table>"
        )
        assert rows[1][0].text == "Café Era"
        assert rows[1][1].text == "Song & Co"

    def test_colspan_pads_cells(self):
        rows = extract_table("<table><tr><td colspan='3'>wide</td><td>end</td></tr></table>")
        assert len(rows[0]) == 4
        assert rows[0][0].text == "wide" and rows[0][3].text == "end"

    def test_br_becomes_newline_and_link_lines_tracked(self):
        rows = extract_table(
            "<table><tr><td>line1<br>"
            '<a href="https://x.test/a">link on line 2</a></td></tr></table>'
        )
        cell = rows[0][0]
        assert cell.text == "line1\nlink on line 2"
        assert cell.links == ["https://x.test/a"]
        assert cell.link_lines == [1]

    def test_colspan_preserves_column_indices(self):
        html = """
        <table>
          <tr><td>Era</td><td>Name</td><td>Notes</td><td>Quality</td></tr>
          <tr><td colspan="2">Merged Era+Name</td><td>note text</td><td>CD Quality</td></tr>
        </table>
        """
        rows = extract_table(html)
        assert len(rows[1]) == 4
        assert rows[1][0].text.strip() == "Merged Era+Name"
        assert rows[1][1].text.strip() == ""
        assert rows[1][2].text.strip() == "note text"
        assert rows[1][3].text.strip() == "CD Quality"


class TestColumnHeaderNormalization:
    """2026-07-20 sweep findings: colon-suffixed headers ('Track Titles:',
    'Producers:', 'Category:') and a few unambiguous alias gaps ('Song',
    'Record Date', 'Release/Leaked Date') dropped whole columns across
    dozens of trackers."""

    def _detect(self, *headers):
        from src.parser import _Cell, detect_columns
        return detect_columns([_Cell(text=h) for h in headers])

    def test_trailing_colon_stripped(self):
        col_map = self._detect("Era:", "Track Titles:", "Notes:", "Links:")
        assert col_map.get("era") == 0
        assert col_map.get("name") == 1
        assert col_map.get("notes") == 2
        assert col_map.get("links") == 3

    def test_song_alias(self):
        assert self._detect("Era", "Song", "Notes").get("name") == 1

    def test_record_date_alias(self):
        assert self._detect("Era", "Name", "Record Date").get("date_of_recording") == 2

    def test_release_leaked_date_alias(self):
        assert self._detect("Era", "Name", "Release/Leaked Date:").get("leak_date") == 2


class TestDroppedColumns:
    def test_unknown_header_surfaced(self):
        from src.parser import _Cell, detect_dropped_columns
        header = [_Cell(text="Era"), _Cell(text="Name"), _Cell(text="Bit Rate"), _Cell(text="Quality")]
        col_map = detect_columns(header)
        dropped = detect_dropped_columns(header, col_map)
        assert "Bit Rate" in dropped and "Era" not in dropped and "Quality" not in dropped

    def test_fully_mapped_header_drops_nothing(self):
        from src.parser import _Cell, detect_dropped_columns
        header = [_Cell(text="Era"), _Cell(text="Name"), _Cell(text="Notes"), _Cell(text="Quality")]
        assert detect_dropped_columns(header, detect_columns(header)) == []


class TestParserRobustness:
    def _parse(self, html):
        from src.parser import parse_sheet
        return parse_sheet(html, "Test Artist")

    def test_empty_document(self):
        assert self._parse("").eras == []

    def test_document_without_table(self):
        assert self._parse("<html><body><p>nothing here</p></body></html>").eras == []

    def test_empty_table(self):
        assert self._parse("<table></table>").eras == []

    def test_unclosed_tags(self):
        assert self._parse("<table><tr><td>Era<td>Name<tr><td>Yeezus<td>New Song").name == "Test Artist"

    def test_nested_table_does_not_crash(self):
        html = (
            "<table><tr><td>Era</td><td>Name</td></tr>"
            "<tr><td><table><tr><td>inner</td></tr></table></td><td>Song A</td></tr></table>"
        )
        assert self._parse(html).name == "Test Artist"

    def test_missing_columns(self):
        html = "<table><tr><td>Era</td><td>Name</td></tr><tr><td>Yeezus</td><td>Some Song</td></tr></table>"
        assert self._parse(html).name == "Test Artist"

    def test_unicode_era_and_song_names(self):
        html = (
            "<table><tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            "<tr><td>ROSALÍA Été</td><td>Süß Song 🎵</td><td>geëky note</td><td></td></tr></table>"
        )
        assert self._parse(html).name == "Test Artist"


class TestParseFileEncoding:
    def test_non_utf8_file_falls_back(self, tmp_path):
        html = "<html><body><table><tr><td>Era</td><td>Don’t Stop</td></tr></table></body></html>"
        p = tmp_path / "tracker.html"
        p.write_bytes(html.encode("cp1252"))
        assert parse_file(p, "Test Artist").name == "Test Artist"


class TestPlaceholderGrouping:
    def _era(self):
        from src.models import Era, Section
        return Era(name="Test Era", sections=[Section()]), {}

    def _add(self, era, index, **kw):
        from src.models import SongVersion
        from src.parser import _add_version_to_era
        _add_version_to_era(era, SongVersion(**kw), index)

    def _songs(self, era):
        return [s for sec in era.sections for s in sec.songs]

    def test_placeholder_names_not_grouped(self):
        era, index = self._era()
        for i in range(3):
            self._add(era, index, name="???", notes=f"unknown song {i}")
        songs = self._songs(era)
        assert len(songs) == 3 and all(len(s.versions) == 1 for s in songs)

    def test_placeholder_with_tag_not_grouped(self):
        era, index = self._era()
        self._add(era, index, name="??? [V2]", version_tag="V2", notes="beat A")
        self._add(era, index, name="??? [V2]", version_tag="V2", notes="beat B")
        assert len(self._songs(era)) == 2

    def test_normal_names_still_group(self):
        era, index = self._era()
        self._add(era, index, name="Song [V1]", version_tag="V1")
        self._add(era, index, name="Song [V2]", version_tag="V2")
        songs = self._songs(era)
        assert len(songs) == 1 and len(songs[0].versions) == 2

    def test_placeholder_with_shared_alt_title_groups(self):
        era, index = self._era()
        self._add(era, index, name="???", alt_titles=["TIME2TIME"], notes="v1")
        self._add(era, index, name="???", alt_titles=["Time2Time"], notes="v2")
        songs = self._songs(era)
        assert len(songs) == 1 and len(songs[0].versions) == 2

    def test_placeholder_with_different_alt_titles_not_grouped(self):
        era, index = self._era()
        self._add(era, index, name="???", alt_titles=["Time2Time"])
        self._add(era, index, name="???", alt_titles=["You Know It"])
        assert len(self._songs(era)) == 2

    def test_placeholder_alt_title_does_not_group_with_titleless(self):
        era, index = self._era()
        self._add(era, index, name="???", alt_titles=["Time2Time"])
        self._add(era, index, name="???")
        assert len(self._songs(era)) == 2

    def test_placeholder_any_shared_alt_title_groups(self):
        era, index = self._era()
        self._add(era, index, name="??? [V1]", version_tag="V1", alt_titles=["???. Bon Iver", "Time2Time"])
        self._add(era, index, name="???", alt_titles=["???. Bon Iver"])
        self._add(era, index, name="??? [V2]", version_tag="V2", alt_titles=["Time2Time"])
        songs = self._songs(era)
        assert len(songs) == 1 and len(songs[0].versions) == 3


class TestMiscTabUnits:
    def test_empty_html(self):
        from src.parser import parse_misc_tab
        assert parse_misc_tab("<html><body>no table</body></html>", "misc") == []

    def test_synthetic_era_header_grouping(self):
        from src.parser import parse_misc_tab
        html = """
        <table>
          <tr><td>Era</td><td>Name</td><td>Notes</td><td>Type</td><td>Link(s)</td></tr>
          <tr><td>2 Released 1 Unreleased</td><td>Era One</td><td></td><td></td><td></td></tr>
          <tr><td></td><td>Entry A</td><td>note</td><td>Video</td><td>https://example.com/a</td></tr>
          <tr><td>Era Two</td><td>Entry B</td><td></td><td>Freestyle</td><td></td></tr>
        </table>
        """
        entries = parse_misc_tab(html, "misc")
        assert [(e.era_name, e.name) for e in entries] == [("Era One", "Entry A"), ("Era Two", "Entry B")]
        assert entries[0].links == ["https://example.com/a"]

    def test_artist_serializes_misc_entries(self):
        from src.models import Artist, MiscEntry
        data = Artist(name="X", slug="x", misc_entries=[MiscEntry(name="A", source_tab="misc")]).dict()
        assert data["misc_entries"][0]["name"] == "A"
        assert data["misc_entries"][0]["source_tab"] == "misc"

    def test_artist_default_empty(self):
        from src.models import Artist
        assert Artist(name="X", slug="x").dict()["misc_entries"] == []
