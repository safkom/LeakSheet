"""Regression test for a real bug found against yetracker.net: a URL whose
GID fragment points at the Misc tab itself (e.g. copied from the browser
while viewing that tab) was silently parsed as if it were the main
eras/songs tab, because parse_sheet's Era/Name/Available/Quality columns are
similar enough to the Misc tab's grammar to extract a plausible-looking but
wrong "eras" list from it — which then skipped discovery of the real main
tab and skipped parsing the Misc tab as misc entries entirely.

The fix classifies the requested GID against the workbook's tab listing
before trusting parse_sheet on it. These tests cover the two pure functions
that decision is built from (async_fetch_and_parse uses _get_content_tabs),
using the exact tab-listing shape (and the exact "Misc" tab name) that
yetracker.net's real page embeds.
"""

from src.fetcher import _discover_named_tabs, _get_content_tabs

# Real items.push() JS shape from yetracker.net's /htmlview page (trimmed to
# the fields these functions read).
YETRACKER_TAB_LISTING_JS = """
<script>
items.push({name: "Unreleased", pageUrl: "/htmlview/sheet?headers=true&gid=34972268", gid: "34972268", isSelected: true});
items.push({name: "Released", pageUrl: "/htmlview/sheet?headers=true&gid=762588265", gid: "762588265"});
items.push({name: "Art", pageUrl: "/htmlview/sheet?headers=true&gid=1219860820", gid: "1219860820"});
items.push({name: "Misc", pageUrl: "/htmlview/sheet?headers=true&gid=70063278", gid: "70063278"});
items.push({name: "Groupbuys", pageUrl: "/htmlview/sheet?headers=true&gid=1022200924", gid: "1022200924"});
</script>
"""


class TestDiscoverNamedTabs:
    def test_extracts_every_tab_name_and_gid(self):
        tabs = _discover_named_tabs(YETRACKER_TAB_LISTING_JS)
        assert tabs["34972268"] == "Unreleased"
        assert tabs["1219860820"] == "Art"
        assert tabs["70063278"] == "Misc"
        assert tabs["1022200924"] == "Groupbuys"

    def test_empty_html_yields_no_tabs(self):
        assert _discover_named_tabs("<html><body>no tabs here</body></html>") == {}


class TestContentTabClassification:
    def test_identifies_the_misc_tab_gid(self):
        tabs = _discover_named_tabs(YETRACKER_TAB_LISTING_JS)
        by_kind = {kind: gid for gid, kind, _name in _get_content_tabs(tabs)}
        assert by_kind["misc"] == "70063278"

    def test_main_and_art_tabs_are_not_content(self):
        tabs = _discover_named_tabs(YETRACKER_TAB_LISTING_JS)
        content_gids = {gid for gid, _kind, _name in _get_content_tabs(tabs)}
        assert "34972268" not in content_gids  # Unreleased (main tab)
        assert "1219860820" not in content_gids  # Art
        assert "1022200924" not in content_gids  # Groupbuys (deliberately unparsed)

    def test_music_videos_tab_is_classified_separately(self):
        tabs = {"1": "Unreleased", "2": "Music Videos"}
        assert _get_content_tabs(tabs) == [("2", "music_videos", "Music Videos")]

    def test_misc_sorts_before_music_videos(self):
        tabs = {"1": "Music Videos", "2": "Misc"}
        assert _get_content_tabs(tabs) == [
            ("2", "misc", "Misc"),
            ("1", "music_videos", "Music Videos"),
        ]

    def test_no_content_tabs(self):
        tabs = {"1": "Unreleased", "2": "Art", "3": "Groupbuys"}
        assert _get_content_tabs(tabs) == []

    def test_this_is_the_exact_decision_the_gid_shortcut_relies_on(self):
        """Mirrors `gid_is_misc_tab = gid in {g for g, _k, _n in
        _get_content_tabs(named_tabs)}` from async_fetch_and_parse for the
        real yetracker.net Misc tab GID — this must be True so the
        gid-shortcut skips parse_sheet and falls through to full tab
        discovery instead."""
        tabs = _discover_named_tabs(YETRACKER_TAB_LISTING_JS)
        requested_gid = "70063278"  # what a URL like ".../#gid=70063278" carries
        gid_is_misc_tab = requested_gid in {
            g for g, _kind, _n in _get_content_tabs(tabs)
        }
        assert gid_is_misc_tab is True
