"""Pure-function unit tests for URL handling and tab discovery in src.fetcher.

No network: these exercise the deterministic helpers that decide which sheet tab
becomes the main tracker. The end-to-end wiring is covered in test_tab_selection.
"""

from __future__ import annotations

import pytest

from src.fetcher import (
    _build_sheet_html_url,
    _clean_tab_name,
    _discover_gids,
    _discover_named_tabs,
    _extract_gid_from_url,
    _extract_sheet_id,
    _get_art_tab_gid,
    _get_content_tabs,
    _get_misc_tabs,
    _get_unreleased_tab_gid,
    _normalize_url,
    _prioritize_gids,
)
from tests.conftest import build_htmlview_base


class TestNormalizeUrl:
    def test_google_variants_collapse_to_htmlview(self):
        for variant in (
            "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=0",
            "https://docs.google.com/spreadsheets/d/ABC123/htmlview",
            "docs.google.com/spreadsheets/d/ABC123/view?usp=sharing",
            "https://docs.google.com/spreadsheets/u/0/d/ABC123/edit",
        ):
            assert _normalize_url(variant) == "https://docs.google.com/spreadsheets/d/ABC123/htmlview"

    def test_custom_domain_gets_scheme_and_trailing_slash(self):
        assert _normalize_url("yetracker.net") == "https://yetracker.net/"
        assert _normalize_url("https://yetracker.net") == "https://yetracker.net/"

    def test_custom_domain_path_preserved(self):
        assert _normalize_url("https://yetracker.net/other") == "https://yetracker.net/other"


class TestSheetIdAndGid:
    def test_extract_sheet_id(self):
        assert _extract_sheet_id("https://docs.google.com/spreadsheets/d/ABC123/htmlview") == "ABC123"
        assert _extract_sheet_id("https://docs.google.com/spreadsheets/u/2/d/XYZ789/edit") == "XYZ789"
        assert _extract_sheet_id("https://yetracker.net/") is None

    def test_extract_gid_from_url(self):
        assert _extract_gid_from_url("https://x/htmlview#gid=123") == "123"
        assert _extract_gid_from_url("https://x/htmlview?gid=456") == "456"
        assert _extract_gid_from_url("https://x/htmlview") is None


class TestBuildSheetHtmlUrl:
    def test_google(self):
        out = _build_sheet_html_url("https://docs.google.com/spreadsheets/d/ABC/htmlview", "77")
        assert out == "https://docs.google.com/spreadsheets/d/ABC/htmlview/sheet?headers=true&gid=77"

    def test_custom_domain(self):
        out = _build_sheet_html_url("https://yetracker.net/", "5")
        assert out == "https://yetracker.net/htmlview/sheet?headers=true&gid=5"


class TestTabDiscovery:
    BASE = build_htmlview_base({
        "100": "Unreleased", "200": "Misc", "300": "🖼️ Art", "400": "Recent",
    })

    def test_discover_gids_in_order_deduped(self):
        assert _discover_gids(self.BASE) == ["100", "200", "300", "400"]

    def test_discover_named_tabs(self):
        tabs = _discover_named_tabs(self.BASE)
        assert tabs["100"] == "Unreleased"
        assert tabs["400"] == "Recent"

    def test_classifiers(self):
        tabs = _discover_named_tabs(self.BASE)
        assert _get_unreleased_tab_gid(tabs) == "100"
        assert _get_art_tab_gid(tabs) == "300"        # emoji stripped before match
        assert _get_misc_tabs(tabs) == [("200", "misc")]

    def test_prioritize_puts_unreleased_first_and_drops_secondary(self):
        gids = _discover_gids(self.BASE)
        reordered, art_gid, unreleased_gid, misc_tabs = _prioritize_gids(self.BASE, gids)
        assert unreleased_gid == "100"
        assert art_gid == "300"
        # Post-PR #10: content tabs carry (gid, kind, display_name).
        assert misc_tabs == [("200", "misc", "Misc")]
        assert reordered[0] == "100"           # unreleased tried first
        assert "300" not in reordered          # art excluded from candidates
        assert "200" not in reordered          # misc excluded from candidates

    def test_prioritize_without_unreleased_keeps_candidate_order(self):
        base = build_htmlview_base({"100": "Songs", "400": "Recent"})
        gids = _discover_gids(base)
        reordered, art_gid, unreleased_gid, misc_tabs = _prioritize_gids(base, gids)
        assert unreleased_gid is None
        assert reordered == ["100", "400"]


# ---------------------------------------------------------------------------
# Tab discovery: JS unescaping, emoji cleaning, kind classification
# (ported from PR #10's test_tabs.py)
# ---------------------------------------------------------------------------

# JS taken from real htmlview pages: names may contain escaped slashes and
# hex escapes (\x26 == "&").
TAB_JS = """
items.push({name: "Unreleased", pageUrl: "x", gid: "100"});
items.push({name: "\\ud83c\\udfc6 Grails \\/ \\ud83e\\udd47Wanted", pageUrl: "x", gid: "200"});
items.push({name: "BPM \\x26 Keys", pageUrl: "x", gid: "300"});
items.push({name: "\\ud83d\\udcfb Released", pageUrl: "x", gid: "400"});
"""


class TestDiscoveryUnescaping:
    def test_escaped_slash_decoded(self):
        assert _discover_named_tabs(TAB_JS)["200"] == "🏆 Grails / 🥇Wanted"

    def test_hex_escape_decoded(self):
        assert _discover_named_tabs(TAB_JS)["300"] == "BPM & Keys"

    def test_unicode_escape_decoded(self):
        assert _discover_named_tabs(TAB_JS)["400"] == "📻 Released"

    def test_lone_surrogate_does_not_raise(self):
        # A truncated emoji escape must not abort tab discovery.
        js = 'items.push({name: "\\ud83c Broken", pageUrl: "x", gid: "9"});'
        tabs = _discover_named_tabs(js)
        assert "9" in tabs  # name survives in some readable form


class TestTabNameCleaning:
    def test_enclosed_alphanumeric_emoji_stripped(self):
        # 🆕 is U+1F195 (Enclosed Alphanumeric Supplement)
        assert _clean_tab_name("🆕 Recent") == "recent"

    def test_misc_technical_emoji_stripped(self):
        # ⏭ is U+23ED (Miscellaneous Technical)
        assert _clean_tab_name("⏭️ Tracklists") == "tracklists"

    def test_existing_emoji_still_stripped(self):
        assert _clean_tab_name("⭐ Best Of") == "best of"
        assert _clean_tab_name("🗑️Worst Of") == "worst of"


class TestContentTabClassification:
    @staticmethod
    def _tabs(**named):
        return _get_content_tabs({gid: name for gid, name in named.items()})

    def test_released_tab_classified(self):
        assert self._tabs(g1="📻 Released") == [("g1", "released", "📻 Released")]

    def test_best_worst_stems_classified(self):
        tabs = self._tabs(g1="⭐ Best Of", g2="🗑️ Worst Of", g3="🌱 Stems")
        assert {kind for _, kind, _ in tabs} == {"best_of", "worst_of", "stems"}

    def test_badge_tabs_get_dedicated_kinds(self):
        # Highlight tabs classify with their own kinds so the loader routes
        # them to badge annotation instead of pages.
        tabs = self._tabs(g1="🏆 Grails / 🥇Wanted", g2="✨ Special", g3="Wanted")
        assert {kind for _, kind, _ in tabs} == {"grails", "special", "wanted"}

    def test_fakes_and_other_content_tabs_classified(self):
        tabs = self._tabs(g1="Fakes", g2="🎤 Performances", g3="Remixes")
        assert {kind for _, kind, _ in tabs} == {"fakes", "other"}

    def test_non_song_tabs_excluded(self):
        tabs = self._tabs(
            g1="Groupbuys", g2="⏭️ Tracklists", g3="🆕 Recent",
            g4="Key", g5="Socials", g6="Tours", g7="💿 Album Copies",
        )
        assert tabs == []

    def test_misc_and_music_videos_included(self):
        tabs = self._tabs(g1="Misc.", g2="Music Videos")
        assert ("g1", "misc", "Misc.") in tabs
        assert ("g2", "music_videos", "Music Videos") in tabs

    def test_misc_sorted_first(self):
        assert self._tabs(g1="📻 Released", g2="Misc.")[0][1] == "misc"

    def test_main_and_art_tabs_not_content(self):
        assert self._tabs(g1="Unreleased", g2="Art") == []

    def test_legacy_get_misc_tabs_shape_unchanged(self):
        assert _get_misc_tabs({"1": "Misc.", "2": "📻 Released"}) == [("1", "misc")]
