"""Pure-function unit tests for URL handling and tab discovery in src.fetcher.

No network: these exercise the deterministic helpers that decide which sheet tab
becomes the main tracker. The end-to-end wiring is covered in test_tab_selection.
"""

from __future__ import annotations

import pytest

from src.fetcher import (
    _build_sheet_html_url,
    _discover_gids,
    _discover_named_tabs,
    _extract_gid_from_url,
    _extract_sheet_id,
    _get_art_tab_gid,
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
        assert misc_tabs == [("200", "misc")]
        assert reordered[0] == "100"           # unreleased tried first
        assert "300" not in reordered          # art excluded from candidates
        assert "200" not in reordered          # misc excluded from candidates

    def test_prioritize_without_unreleased_keeps_candidate_order(self):
        base = build_htmlview_base({"100": "Songs", "400": "Recent"})
        gids = _discover_gids(base)
        reordered, art_gid, unreleased_gid, misc_tabs = _prioritize_gids(base, gids)
        assert unreleased_gid is None
        assert reordered == ["100", "400"]
