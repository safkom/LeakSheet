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

    # The families below were absent until 2026-08 and account for ~2,400 rows
    # across the cached trackers. Leaving them out did two things: the tag
    # stayed in the displayed title, AND _add_version_to_era groups on the
    # tag-stripped name, so "90210 [Demo 8]" and "90210 [Demo 9]" became two
    # separate songs instead of two versions of one.
    @pytest.mark.parametrize("raw,tag,base", [
        ("90210 [Demo 8]", "Demo 8", "90210"),
        ("Dis Side [Demo]", "Demo", "Dis Side"),
        ("Whose House [OG File]", "OG File", "Whose House"),
        ("Track [Master File]", "Master File", "Track"),
        ("Track [Instrumental]", "Instrumental", "Track"),
        ("Track [Remix]", "Remix", "Track"),
        ("Track [Final]", "Final", "Track"),
        ("Track [Final Mix]", "Final Mix", "Track"),
        ("Track [Final Mix 2]", "Final Mix 2", "Track"),
        ("Track [Rough Mix]", "Rough Mix", "Track"),
        ("Track [Mix A]", "Mix A", "Track"),
        ("Track [Live]", "Live", "Track"),
    ])
    def test_late_added_tag_families(self, raw, tag, base):
        assert extract_version_tag(raw) == (tag, base)

    @pytest.mark.parametrize("raw", [
        "Track [Mixtape]",   # "Mix [A-Z]" must not eat a longer word
        "Track [Deluxe]",
        "Track [Snippet]",
        "Track [2019]",
    ])
    def test_unrecognised_brackets_stay_in_the_title(self, raw):
        assert extract_version_tag(raw) == (None, raw)

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
        c = parse_song_credits(raw)
        assert c.title == "10 in a Benz"
        assert c.featuring == "Rhymefest"
        assert c.producers == "Kanye West & Andy C."
        assert c.collaboration == "Go Getters"
        assert c.refs is None
        assert c.alt_titles == ["On 10 in a Benz"]

    def test_feat_and_prod_only(self):
        from src.models import parse_song_credits
        c = parse_song_credits("3 Minutes of Watts\n(feat. J-Rock) (prod. Don-P)")
        assert c.title == "3 Minutes of Watts"
        assert c.featuring == "J-Rock" and c.producers == "Don-P" and c.collaboration is None and c.alt_titles == []

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
        c = parse_song_credits("RATHER LIE [Clean](ref. Keith Lawson)")
        assert c.title == "RATHER LIE [Clean]" and c.refs == "Keith Lawson"

    def test_alt_title_only(self):
        from src.models import parse_song_credits
        title, *_, alts = parse_song_credits("On My Own\n(My Own)")
        assert title == "On My Own" and alts == ["My Own"]

    def test_multiple_alt_titles(self):
        from src.models import parse_song_credits
        c = parse_song_credits("I'm Him\n(prod. Hykeem Carter)\n(I'm The Man, Thank God)")
        # 2026-07-17 (PR #10): comma-separated parenthetical aliases split into
        # individual alt titles — see TestCommaAltTitles for the stay-whole guards.
        assert c.title == "I'm Him" and c.producers == "Hykeem Carter" and c.alt_titles == ["I'm The Man", "Thank God"]

    def test_no_credits(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Ain't No Money")
        assert c.title == "Ain't No Money"
        assert (c.featuring, c.producers, c.collaboration, c.refs, c.alt_titles) == (None, None, None, None, [])

    def test_remix_stays_in_title(self):
        from src.models import parse_song_credits
        title, feat, *_ = parse_song_credits("Black Skinhead (Remix) [V3]")
        assert title == "Black Skinhead (Remix) [V3]" and feat is None

    def test_complex_featuring(self):
        from src.models import parse_song_credits
        raw = "All I Need \n(with Go Getters) (feat. Kanye West, Mikkey Halsted, Taji & Miss Criss) (prod. AllDay & Kanye West) \n(All I Have)"
        c = parse_song_credits(raw)
        assert c.title == "All I Need"
        assert "Kanye West" in c.featuring and "Mikkey Halsted" in c.featuring
        assert c.collaboration == "Go Getters" and "AllDay" in c.producers and c.alt_titles == ["All I Have"]

    def test_artist_prefix_stays_in_title(self):
        from src.models import parse_song_credits
        title, feat, prod, *_ = parse_song_credits("Jay Rock - To The Top\n(feat. K-Dot) (prod. DJ Mano)")
        assert title == "Jay Rock - To The Top" and feat == "K-Dot" and prod == "DJ Mano"

    def test_carti_format(self):
        from src.models import parse_song_credits
        c = parse_song_credits("36 Villainz\n(prod. Cold Hart & DJ Anuedy)\n(36IllVillianz)")
        assert c.title == "36 Villainz" and c.producers == "Cold Hart & DJ Anuedy" and c.alt_titles == ["36IllVillianz"]


class TestBracketStyleCredits:
    """Bracket-delimited credits — the Travis Scott tracker's house style.

    Before this was supported, every '[prod. X]' line fell through to
    alt_titles and the app rendered it as 'aka [prod. Allen Ritter]'
    (1097 of 1311 Travis versions).
    """

    def test_bracket_prod(self):
        from src.models import parse_song_credits
        c = parse_song_credits("90210 [Demo 8]\n[prod. Allen Ritter]")
        assert c.title == "90210 [Demo 8]"
        assert c.producers == "Allen Ritter"
        assert c.alt_titles == []

    def test_bracket_feat_ref_with(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Song\n[feat. Young Thug] [ref. Kacy Hill] [with Go Getters]")
        assert c.featuring == "Young Thug"
        assert c.refs == "Kacy Hill"
        assert c.collaboration == "Go Getters"
        assert c.alt_titles == []

    def test_bracket_director(self):
        from src.models import parse_song_credits
        c = parse_song_credits("silent film [Music Video]\n[dir. Ovrkast.]")
        assert c.director == "Ovrkast." and c.alt_titles == []

    def test_paren_director(self):
        from src.models import parse_song_credits
        assert parse_song_credits("Clip\n(dir. Dave Meyers)").director == "Dave Meyers"

    def test_mixed_delimiters_in_one_name(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Maria I'm Drunk [Demo 2]\n(feat. Young Thug)\n[prod. Metro Boomin]")
        assert c.featuring == "Young Thug"
        assert c.producers == "Metro Boomin"
        assert c.alt_titles == []

    def test_version_tag_is_not_a_credit(self):
        from src.models import parse_song_credits
        # Bracket support must not touch [V1] / [Demo 8] / [Clean] tags.
        c = parse_song_credits("Dis Side [Demo]\n[prod. Ging]")
        assert c.title == "Dis Side [Demo]" and c.producers == "Ging"

    def test_mismatched_delimiters_still_parse(self):
        from src.models import parse_song_credits
        # Hand-typed sheets mix the styles by accident — three such rows
        # exist on the live Travis tracker ("[prod. Travis Scott)").
        assert parse_song_credits("Song\n[prod. Nobody)").producers == "Nobody"
        assert parse_song_credits("Song\n(prod. Nobody]").producers == "Nobody"

    def test_semicolon_separates_credits_in_one_group(self):
        from src.models import parse_song_credits
        # The Travis tracker packs several credits into one group. ';' was not
        # a delimiter anywhere, so `ref` swallowed the whole body up to the
        # closer and `feat` — not being bracket-prefixed — matched nothing.
        # Real cell, Owl Pharaoh era.
        c = parse_song_credits(
            "Kanye West - No No No No\n"
            "(ref. Travis Scott; feat. 2 Chainz & The-Dream)\n"
            "[prod. Sak Pase & Travis Scott]"
        )
        assert c.title == "Kanye West - No No No No"
        assert c.refs == "Travis Scott"
        assert c.featuring == "2 Chainz & The-Dream"
        assert c.producers == "Sak Pase & Travis Scott"
        assert c.alt_titles == []

    def test_comma_separates_credits_only_when_a_keyword_follows(self):
        from src.models import parse_song_credits
        # A comma inside a name list belongs to the value…
        assert parse_song_credits("X\n(feat. Rhymefest, Kanye West)").featuring == (
            "Rhymefest, Kanye West"
        )
        # …but one before another keyword separates two credits.
        c = parse_song_credits("X\n(prod. A & B, ref. C)")
        assert c.producers == "A & B" and c.refs == "C"

    def test_keyword_must_open_the_group(self):
        from src.models import parse_song_credits
        # Otherwise "(Some Title, prod. X)" would lose its title half, and
        # "(Remix)" would need special-casing.
        c = parse_song_credits("Song\n(Some Alias, prod. X)")
        assert c.producers is None
        # The group survives as an alt title; the comma splitting there is
        # _split_alt_aliases' pre-existing behaviour for alias lists.
        assert c.alt_titles == ["Some Alias", "prod. X"]

    def test_prod_spelling_variants(self):
        from src.models import parse_song_credits
        assert parse_song_credits("X (Prod By Metro)").producers == "Metro"
        assert parse_song_credits("X (produced by Metro)").producers == "Metro"
        assert parse_song_credits("X (prod. Metro)").producers == "Metro"

    def test_w_slash_is_a_collaboration(self):
        from src.models import parse_song_credits
        assert parse_song_credits("X (w/ Kanye)").collaboration == "Kanye"

    def test_removing_an_inline_group_does_not_leave_a_double_space(self):
        from src.models import parse_song_credits
        assert parse_song_credits("Title (feat. A) Remix").title == "Title Remix"

    def test_multiline_credit_is_not_parsed(self):
        from src.models import parse_song_credits
        # A credit whose closer is on the next line stays an alt title:
        # spanning newlines would let an unclosed "(prod. " swallow real
        # alt-title lines. One such row exists on Travis; not worth it.
        c = parse_song_credits("Song\n[prod. TM88,\nMacnificent]")
        assert c.producers is None

    def test_genuine_alt_title_still_survives(self):
        from src.models import parse_song_credits
        c = parse_song_credits("???\n[prod. Ging]\n(Flavors)")
        assert c.producers == "Ging" and c.alt_titles == ["Flavors"]


class TestAliasLabelStripping:
    """Some trackers label the alias line rather than just writing it.

    Travis uses "(AKA: iLLamerica)" on 220 of its 259 alias lines. The field
    IS the alias, so the label is redundant — and a client that prefixes its
    own "aka" rendered it twice ("aka AKA: iLLamerica").
    """

    def test_aka_label_dropped(self):
        from src.models import parse_song_credits
        assert parse_song_credits("iLLemerica\n(AKA: iLLamerica)").alt_titles == ["iLLamerica"]

    def test_dotted_and_dashed_forms(self):
        from src.models import parse_song_credits
        assert parse_song_credits("X\n(a.k.a. Foo)").alt_titles == ["Foo"]
        assert parse_song_credits("X\n(AKA - Foo)").alt_titles == ["Foo"]

    def test_unparenthesised_line(self):
        from src.models import parse_song_credits
        assert parse_song_credits("X\nAKA: Bare Line").alt_titles == ["Bare Line"]

    def test_label_is_dropped_before_the_comma_split(self):
        from src.models import parse_song_credits
        # Otherwise the first alias keeps the label and the rest don't.
        assert parse_song_credits(
            "X\n(AKA: First Name, Second Name)"
        ).alt_titles == ["First Name", "Second Name"]

    def test_word_starting_with_aka_is_not_a_label(self):
        from src.models import parse_song_credits
        assert parse_song_credits("X\n(Akashic Records)").alt_titles == ["Akashic Records"]

    def test_bare_label_is_kept_rather_than_emptied(self):
        from src.models import parse_song_credits
        assert parse_song_credits("X\n(AKA)").alt_titles == ["AKA"]

    def test_ordinary_alias_untouched(self):
        from src.models import parse_song_credits
        assert parse_song_credits("On My Own\n(My Own)").alt_titles == ["My Own"]


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

    def test_single_filename(self):
        from src.models import extract_og_filenames
        notes = "OG Filename: Broke My Heart 1\nRest of note"
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
        c = parse_song_credits("???\n(Time2Time, Bon Iver Demo)")
        assert c.alt_titles == ["Time2Time", "Bon Iver Demo"]

    def test_volume_continuation_kept_whole(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Some Song\n(Meet The Woo, Vol. 2)")
        assert c.alt_titles == ["Meet The Woo, Vol. 2"]

    def test_numeric_comma_kept_whole(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Some Song\n(10,000 Days)")
        assert c.alt_titles == ["10,000 Days"]

    def test_roman_numeral_continuation_kept_whole(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Song\n(Hell Of A Life, Pt. II)")
        assert c.alt_titles == ["Hell Of A Life, Pt. II"]

    def test_worded_ordinal_continuation_kept_whole(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Song\n(The Story, Part Two)")
        assert c.alt_titles == ["The Story, Part Two"]

    def test_feat_credit_commas_unaffected(self):
        from src.models import parse_song_credits
        c = parse_song_credits("Some Song\n(feat. Rhymefest, Kanye West)")
        assert c.featuring == "Rhymefest, Kanye West"
        assert c.alt_titles == []


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

    def test_xml_declaration_falls_back_to_stdlib_parser(self):
        """lxml raises ValueError for str input carrying an encoding
        declaration; extract_table must fall back to the stdlib parser
        instead of propagating (seen on mirrored exports)."""
        html = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<html><body><table><tr><td>Era</td><td>Name</td></tr></table></body></html>"
        )
        rows = extract_table(html)
        assert rows[0][0].text == "Era"
        assert rows[0][1].text == "Name"


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


class TestSweepDrivenColumnWiring:
    """User-confirmed mappings (2026-07-20): bare 'Date' → leak_date;
    'Producer(s)' → producers (when the name-cell credit didn't set it);
    'Artist'/'Credited Artist' → the new credited_artists field;
    'File Name'/'Instrumental Name' → og_filenames."""

    HTML = (
        "<table>"
        "<tr><td>Era</td><td>Track Titles:</td><td>Artists:</td><td>Producers:</td>"
        "<td>Date</td><td>File Name</td><td>Links</td></tr>"
        "<tr><td>1 Full</td><td>Demo Era</td><td></td><td></td><td></td><td></td><td></td></tr>"
        "<tr><td>Demo Era</td><td>Glass House</td><td>SynthGuest</td><td>Mathan Beats</td>"
        "<td>March 2, 2012</td><td>glass_house_final</td><td></td></tr>"
        "</table>"
    )

    def _version(self):
        from src.parser import parse_sheet
        artist = parse_sheet(self.HTML, "Test")
        return artist.eras[0].songs[0].primary

    def test_date_column_maps_to_leak_date(self):
        assert self._version().leak_date == "March 2, 2012"

    def test_producer_column_populates_producers(self):
        assert self._version().producers == "Mathan Beats"

    def test_name_cell_credit_beats_producer_column(self):
        from src.parser import parse_sheet
        html = self.HTML.replace("Glass House", "Glass House\n(prod. Inline Credit)")
        v = parse_sheet(html, "Test").eras[0].songs[0].primary
        assert v.producers == "Inline Credit"

    def test_artist_column_populates_credited_artists(self):
        assert self._version().credited_artists == "SynthGuest"

    def test_file_name_column_populates_og_filenames(self):
        v = self._version()
        assert v.og_filenames == ["glass_house_final"]
        assert v.og_filename == "glass_house_final"

    def test_file_name_column_merges_with_notes_og_no_dupes(self):
        # A sheet may carry BOTH a File Name column and an 'OG Filename:'
        # notes line; both must land in og_filenames without duplicates.
        from src.parser import parse_sheet
        html = (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>File Name</td><td>Links</td></tr>"
            "<tr><td>1 Full</td><td>Demo Era</td><td></td><td></td><td></td></tr>"
            "<tr><td>Demo Era</td><td>Glass House</td>"
            "<td>OG Filename: glass_house_alt</td><td>glass_house_final</td><td></td></tr>"
            "</table>"
        )
        v = parse_sheet(html, "Test").eras[0].songs[0].primary
        assert v.og_filenames == ["glass_house_final", "glass_house_alt"]


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


class TestContentTabStructuralRows:
    """Era headers and section labels must not surface as entries.

    Content tabs write era headers three ways; only the first was recognised,
    so the other two became fake songs whose "date" was the era description
    and whose "notes" were the era timeline — visible in the app as a song
    called "The College Dropout" with the album blurb under Leak Date.
    """

    @staticmethod
    def _entries():
        from src.parser import parse_misc_tab
        from tests.conftest import read_synthetic
        return parse_misc_tab(read_synthetic("content_tab_structure"), "released")

    def test_only_real_entries_survive(self):
        assert [e.name for e in self._entries()] == [
            "Real Song One",
            "Second Era (Chopped Not Slopped)",
            "Third Song",
            "Type Only",
        ]

    def test_headers_set_the_era_for_rows_beneath_them(self):
        by_name = {e.name: e for e in self._entries()}
        assert by_name["Real Song One"].era_name == "First Era"
        assert by_name["Third Song"].era_name == "Third Era"

    def test_unknown_stats_vocabulary_header_is_not_an_entry(self):
        # "1 Mixtape Tracks" is not in the stats keyword list, and this row
        # spills its prose into the Leak Date column. Recognised by shape.
        names = [e.name for e in self._entries()]
        assert "Second Era" not in names
        assert all(e.date != "The earliest period of the group." for e in self._entries())

    def test_bare_section_labels_dropped(self):
        names = [e.name for e in self._entries()]
        assert "Projects" not in names and "Features" not in names

    def test_song_titled_like_its_own_era_is_kept(self):
        # _era_match_key drops the parenthetical, collapsing this title onto
        # its era name. It has a length and a date, so it is a song.
        e = next(x for x in self._entries() if x.name.startswith("Second Era ("))
        assert e.era_name == "Second Era" and e.length == "5:06"

    def test_row_whose_only_field_is_type_is_kept(self):
        e = next(x for x in self._entries() if x.name == "Type Only")
        assert e.entry_type == "Freestyle"


class TestMiscTabUnits:
    def test_empty_html(self):
        from src.parser import parse_misc_tab
        assert parse_misc_tab("<html><body>no table</body></html>", "misc") == []

    def test_colon_suffixed_headers(self):
        # Same colon-suffix grammar the 2026-07-20 sweep found on main tabs
        # exists on secondary tabs; _misc_header_key must strip it too.
        from src.parser import parse_misc_tab
        html = (
            "<table>"
            "<tr><td>Era:</td><td>Name:</td><td>Type:</td><td>Link(s):</td></tr>"
            "<tr><td>Era One</td><td>Entry A</td><td>Video</td>"
            "<td><a href='https://example.com/a'>l</a></td></tr>"
            "</table>"
        )
        entries = parse_misc_tab(html, "misc")
        assert len(entries) == 1
        assert entries[0].era_name == "Era One"
        assert entries[0].entry_type == "Video"
        assert entries[0].links == ["https://example.com/a"]

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


class TestContentTabEraNamesFromMainTab:
    """A tab's own era column abbreviates: Travis's Released tab files songs
    under "Birds" while the header row reads "Birds In The Trap Sing
    McKnight". The column alone can't spot that header, so the main tab's era
    names are passed in."""

    HTML = (
        "<table>"
        "<tr><td>Era</td><td>Title</td><td>Notes</td><td>Length</td><td>Release Date</td></tr>"
        "<tr><td>Rodeo</td><td>A Rodeo Song</td><td>n</td><td>3:00</td><td>2015</td></tr>"
        "<tr><td></td><td>Birds In The Trap Sing McKnight</td>"
        "<td>Sophomore studio album.</td><td></td><td></td></tr>"
        "<tr><td>Birds</td><td>the ends</td><td>n</td><td>3:21</td><td>2016</td></tr>"
        "</table>"
    )

    def test_abbreviated_era_header_needs_the_main_tab_names(self):
        from src.parser import parse_misc_tab
        # Without them the header is indistinguishable from a song.
        assert "Birds In The Trap Sing McKnight" in [
            e.name for e in parse_misc_tab(self.HTML, "released")
        ]
        # With them it is recognised and drops out.
        entries = parse_misc_tab(
            self.HTML, "released", ["Rodeo", "Birds In The Trap Sing McKnight"]
        )
        assert [e.name for e in entries] == ["A Rodeo Song", "the ends"]

    def test_song_named_after_another_era_does_not_hijack_the_era(self):
        from src.parser import parse_misc_tab
        # A song titled like a DIFFERENT era, with no track data, must not be
        # read as a header — that would re-file every row beneath it.
        html = (
            "<table>"
            "<tr><td>Era</td><td>Title</td><td>Notes</td><td>Length</td></tr>"
            "<tr><td>Rodeo</td><td>Astroworld</td><td>A song, not the era.</td><td></td></tr>"
            "<tr><td>Rodeo</td><td>Another Song</td><td>n</td><td>3:00</td></tr>"
            "</table>"
        )
        entries = parse_misc_tab(html, "released", ["Rodeo", "Astroworld"])
        assert [(e.era_name, e.name) for e in entries] == [
            ("Rodeo", "Astroworld"), ("Rodeo", "Another Song")
        ]


class TestBrokenStatsFormula:
    """A `#REF!` in the era-stats column must not hide era headers.

    Regression for the Future tracker (2026-08): its stats column was a
    broken formula, so `_is_era_header` matched nothing, every era header
    was missed, and all 1019 songs collapsed into a single era literally
    named "#REF!".
    """

    @staticmethod
    def _sheet(stats_a: str, stats_b: str) -> str:
        return (
            "<table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Links</td></tr>"
            f"<tr><td>{stats_a}</td><td>Dirty Sprite</td><td></td><td></td></tr>"
            "<tr><td>Dirty Sprite</td><td>Hey Ho</td><td>n</td>"
            "<td><a href='https://pillows.su/f/x'>l</a></td></tr>"
            f"<tr><td>{stats_b}</td><td>Pluto</td><td></td><td></td></tr>"
            "<tr><td>Pluto</td><td>Turn On The Lights</td><td>n</td>"
            "<td><a href='https://pillows.su/f/y'>l</a></td></tr>"
            "</table>"
        )

    def test_valid_stats_cell_splits_eras(self):
        from src.parser import parse_sheet
        artist = parse_sheet(self._sheet("2 Full", "1 Full"), "Future")
        assert [e.name for e in artist.eras] == ["Dirty Sprite", "Pluto"]

    def test_error_stats_cell_splits_eras_identically(self):
        """Only the stats cell differs from the test above."""
        from src.parser import parse_sheet
        artist = parse_sheet(self._sheet("#REF!", "#REF!"), "Future")
        assert [e.name for e in artist.eras] == ["Dirty Sprite", "Pluto"]

    def test_error_value_is_never_an_era_name(self):
        from src.parser import _looks_like_era_name
        for err in ("#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?"):
            assert _looks_like_era_name(err) is False, err

    def test_real_era_names_still_pass(self):
        from src.parser import _looks_like_era_name
        for name in ("Dirty Sprite", "DS2", "56 Nights"):
            assert _looks_like_era_name(name) is True, name


class TestArtTabCoverSelection:
    """The cover test reads Project Type, not the whole row.

    Regression (2026-08): `\\bcover\\b` was searched across the concatenated
    row, and tracker Notes mention "cover" constantly, so the branch fired on
    nearly every row and each era kept whichever image came first — 18 of 47
    Ye eras ended up showing a different album's artwork.
    """

    HEADER = (
        "<tr><td>Era</td><td>Name</td><td>Project Type</td><td>Notes</td></tr>"
    )

    def test_notes_mentioning_cover_do_not_win(self):
        from src.parser import parse_art_tab
        html = (
            "<table>" + self.HEADER +
            # First row: a single's art. Notes say "cover", Project Type does not.
            "<tr><td>Donda</td><td>Only One</td><td>Single Art</td>"
            "<td>Cover was shot in Paris</td>"
            "<td><img src='https://img/wrong.png'></td></tr>"
            # Second row: the actual album cover.
            "<tr><td>Donda</td><td>Donda</td><td>Front Cover</td><td>n</td>"
            "<td><img src='https://img/right.png'></td></tr>"
            "</table>"
        )
        assert parse_art_tab(html)["donda"] == "https://img/right.png"

    def test_blank_era_cell_carries_forward(self):
        from src.parser import parse_art_tab
        # Continuation rows leave Era blank; the image must stay with Donda
        # rather than being filed under the artwork's own name.
        html = (
            "<table>" + self.HEADER +
            "<tr><td>Donda</td><td>Promo</td><td>Promo Shot</td><td>n</td>"
            "<td><img src='https://img/promo.png'></td></tr>"
            "<tr><td></td><td>Alt Sleeve</td><td>Front Cover</td><td>n</td>"
            "<td><img src='https://img/cover.png'></td></tr>"
            "</table>"
        )
        art = parse_art_tab(html)
        assert art == {"donda": "https://img/cover.png"}
        assert "alt sleeve" not in art

    def test_falls_back_to_first_image_without_a_cover_row(self):
        from src.parser import parse_art_tab
        html = (
            "<table>" + self.HEADER +
            "<tr><td>Yandhi</td><td>Promo</td><td>Promo Shot</td><td>n</td>"
            "<td><img src='https://img/a.png'></td></tr>"
            "</table>"
        )
        assert parse_art_tab(html)["yandhi"] == "https://img/a.png"

    def test_headerless_art_tab_still_parses(self):
        from src.parser import parse_art_tab
        # No header row → row-wide fallback, preserving old behaviour.
        html = (
            "<table>"
            "<tr><td>Graduation</td><td>Front Cover</td>"
            "<td><img src='https://img/g.png'></td></tr>"
            "</table>"
        )
        assert parse_art_tab(html)["graduation"] == "https://img/g.png"


class TestVersionSorting:
    """Version ordering — there was no sort at all before 2026-08.

    Versions arrived in spreadsheet row order, so [Demo 10] landed next to
    [Demo 1] and a song's V-takes were interleaved with its demos.
    """

    def test_numeric_tags_sort_numerically_not_lexically(self):
        from src.models import version_sort_key
        tags = ["V10", "V2", "V1"]
        ordered = [t for t, _ in sorted(
            ((t, i) for i, t in enumerate(tags)),
            key=lambda p: version_sort_key(*p),
        )]
        assert ordered == ["V1", "V2", "V10"]

    def test_demos_sort_numerically_and_after_v_takes(self):
        from src.models import version_sort_key
        tags = ["Demo 10", "V2", "Demo", "V1", "Demo 2"]
        ordered = [t for t, _ in sorted(
            ((t, i) for i, t in enumerate(tags)),
            key=lambda p: version_sort_key(*p),
        )]
        assert ordered == ["V1", "V2", "Demo", "Demo 2", "Demo 10"]

    def test_untagged_and_unknown_tags_keep_sheet_order_at_the_end(self):
        from src.models import version_sort_key
        tags = ["OG File", None, "Alt", "V1"]
        ordered = [t for t, _ in sorted(
            ((t, i) for i, t in enumerate(tags)),
            key=lambda p: version_sort_key(*p),
        )]
        # V1 leads; the rest keep their original relative order — inventing an
        # order for unrecognised tags would be worse than leaving them alone.
        assert ordered == ["V1", "OG File", None, "Alt"]

    def test_sort_is_stable_for_equal_keys(self):
        from src.models import version_sort_key
        keys = [version_sort_key("Demo 3", i) for i in range(3)]
        assert keys == sorted(keys)
        assert [k[2] for k in keys] == [0, 1, 2]

    def test_era_versions_are_sorted_after_parsing(self):
        """End-to-end: the sort actually runs on a parsed era."""
        from src.models import Era, Section, Song, SongVersion
        from src.parser import _sort_era_versions

        def v(tag):
            return SongVersion(name=f"Track [{tag}]", version_tag=tag)

        song = Song(base_name="Track", versions=[v("Demo 10"), v("V2"), v("Demo 2"), v("V1")])
        era = Era(name="E", sections=[Section(name="", songs=[song])])
        _sort_era_versions(era)
        assert [x.version_tag for x in song.versions] == ["V1", "V2", "Demo 2", "Demo 10"]
