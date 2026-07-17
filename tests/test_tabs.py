"""Tab taxonomy tests — discovery unescaping, emoji cleaning, kind
classification, and the additive Artist.tabs API surface.

Added 2026-07-17 for the extra-tabs feature (Released / Best Of / Worst Of /
Stems / other content tabs). Keyword sets were derived from a live census of
the Ye / Travis / Kendrick / Carti trackers.
"""

from src.fetcher import (
    _clean_tab_name,
    _discover_named_tabs,
    _get_content_tabs,
    _get_misc_tabs,
)
from src.models import Artist, MiscEntry, TabSection
from src.parser import parse_misc_tab


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
        tabs = _discover_named_tabs(TAB_JS)
        assert tabs["200"] == "🏆 Grails / 🥇Wanted"

    def test_hex_escape_decoded(self):
        tabs = _discover_named_tabs(TAB_JS)
        assert tabs["300"] == "BPM & Keys"

    def test_unicode_escape_decoded(self):
        tabs = _discover_named_tabs(TAB_JS)
        assert tabs["400"] == "📻 Released"


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
        tabs = self._tabs(g1="📻 Released")
        assert tabs == [("g1", "released", "📻 Released")]

    def test_best_worst_stems_classified(self):
        tabs = self._tabs(g1="⭐ Best Of", g2="🗑️ Worst Of", g3="🌱 Stems")
        kinds = {kind for _, kind, _ in tabs}
        assert kinds == {"best_of", "worst_of", "stems"}

    def test_other_content_tabs_classified(self):
        tabs = self._tabs(g1="🏆 Grails / 🥇Wanted", g2="✨ Special", g3="Fakes")
        assert all(kind == "other" for _, kind, _ in tabs)
        assert len(tabs) == 3

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
        tabs = self._tabs(g1="📻 Released", g2="Misc.")
        assert tabs[0][1] == "misc"

    def test_main_and_art_tabs_not_content(self):
        tabs = self._tabs(g1="Unreleased", g2="Art")
        assert tabs == []

    def test_legacy_get_misc_tabs_shape_unchanged(self):
        named = {"1": "Misc.", "2": "📻 Released"}
        assert _get_misc_tabs(named) == [("1", "misc")]


class TestTabsAPISurface:
    def test_artist_tabs_serialized(self):
        artist = Artist(
            name="Test",
            slug="test",
            tabs=[
                TabSection(
                    kind="released",
                    name="📻 Released",
                    entries=[
                        MiscEntry(name="Song A", era_name="Era 1", source_tab="released")
                    ],
                )
            ],
        )
        d = artist.model_dump()
        assert d["tabs"][0]["kind"] == "released"
        assert d["tabs"][0]["name"] == "📻 Released"
        assert d["tabs"][0]["entries"][0]["name"] == "Song A"

    def test_tabs_default_empty(self):
        assert Artist(name="Test", slug="test").model_dump()["tabs"] == []


class TestExtraTabParsing:
    RELEASED_HTML = (
        "<table>"
        "<tr><td>Era</td><td>Title</td><td>Notes</td><td>Leak Date</td>"
        "<td>Currently Available</td><td>Link(s)</td></tr>"
        "<tr><td>Donda</td><td>Hurricane</td><td>Final version</td>"
        "<td>Aug 2021</td><td>Full</td>"
        "<td><a href='https://pillows.su/f/abc'>link</a></td></tr>"
        "</table>"
    )

    def test_released_tab_rows_parse_with_kind(self):
        entries = parse_misc_tab(self.RELEASED_HTML, "released")
        assert len(entries) == 1
        e = entries[0]
        assert e.source_tab == "released"
        assert e.name == "Hurricane"
        assert e.era_name == "Donda"
        assert e.date == "Aug 2021"
        assert e.available == "Full"
        assert e.links == ["https://pillows.su/f/abc"]
