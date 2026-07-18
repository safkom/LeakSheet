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

    def test_badge_tabs_get_dedicated_kinds(self):
        # 2026-07-18: highlight tabs classify with their own kinds so the
        # loader can route them to badge annotation instead of pages.
        tabs = self._tabs(g1="🏆 Grails / 🥇Wanted", g2="✨ Special", g3="Wanted")
        kinds = {kind for _, kind, _ in tabs}
        assert kinds == {"grails", "special", "wanted"}

    def test_fakes_and_other_content_tabs_classified(self):
        tabs = self._tabs(g1="Fakes", g2="🎤 Performances", g3="Remixes")
        kinds = {kind for _, kind, _ in tabs}
        assert kinds == {"fakes", "other"}

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


class TestBadgeTabAnnotation:
    """Highlight tabs (Best Of / Worst Of / Special / Grails / Wanted) stamp
    badges onto matching main-tab songs instead of becoming pages."""

    @staticmethod
    def _artist():
        from src.models import Era, Section, Song, SongVersion

        def song(name, badge=None):
            return Song(
                base_name=name,
                versions=[SongVersion(name=name, badge=badge)],
            )

        donda = Era(name="Donda", sections=[Section(songs=[
            song("Hurricane"), song("Jail"),
        ])])
        yeezus = Era(name="Yeezus", sections=[Section(songs=[
            song("New Slaves"), song("Hurricane"), song("Starred", badge="best"),
        ])])
        return Artist(name="Test", slug="test", eras=[donda, yeezus])

    @staticmethod
    def _entry(name, era=""):
        return MiscEntry(name=name, era_name=era, source_tab="best_of")

    def test_era_scoped_match_stamps_badge(self):
        from src.parser import apply_badge_tab
        artist = self._artist()
        applied = apply_badge_tab(artist, "best_of", [self._entry("Hurricane", era="Yeezus")])
        assert applied == 1
        yeezus = artist.eras[1]
        hurricane = next(s for s in yeezus.sections[0].songs if s.base_name == "Hurricane")
        assert hurricane.versions[0].badge == "best"
        # The Donda Hurricane is untouched
        assert artist.eras[0].sections[0].songs[0].versions[0].badge is None

    def test_unique_name_matches_without_era(self):
        from src.parser import apply_badge_tab
        artist = self._artist()
        applied = apply_badge_tab(artist, "worst_of", [self._entry("Jail")])
        assert applied == 1
        assert artist.eras[0].sections[0].songs[1].versions[0].badge == "worst"

    def test_ambiguous_name_without_era_is_skipped(self):
        from src.parser import apply_badge_tab
        artist = self._artist()
        # "Hurricane" exists in two eras — no era given → no guess
        assert apply_badge_tab(artist, "best_of", [self._entry("Hurricane")]) == 0

    def test_existing_badge_never_overwritten(self):
        from src.parser import apply_badge_tab
        artist = self._artist()
        assert apply_badge_tab(artist, "worst_of", [self._entry("Starred", era="Yeezus")]) == 0
        starred = artist.eras[1].sections[0].songs[2]
        assert starred.versions[0].badge == "best"

    def test_version_tags_stripped_before_matching(self):
        from src.parser import apply_badge_tab
        artist = self._artist()
        applied = apply_badge_tab(artist, "grails", [self._entry("New Slaves [V2]", era="Yeezus")])
        assert applied == 1
        assert artist.eras[1].sections[0].songs[0].versions[0].badge == "grail"

    def test_unknown_kind_is_noop(self):
        from src.parser import apply_badge_tab
        artist = self._artist()
        assert apply_badge_tab(artist, "released", [self._entry("Jail")]) == 0
