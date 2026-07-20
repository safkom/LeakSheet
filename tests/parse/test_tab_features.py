"""Tab taxonomy tests — discovery unescaping, emoji cleaning, kind
classification, and the additive Artist.tabs API surface.

Added 2026-07-17 for the extra-tabs feature (Released / Best Of / Worst Of /
Stems / other content tabs). Keyword sets were derived from a live census of
the Ye / Travis / Kendrick / Carti trackers.
"""

from src.models import Artist, MiscEntry, TabSection
from src.parser import parse_misc_tab

# NOTE: tab *discovery* tests (JS unescaping, emoji cleaning, kind
# classification) live in tests/fetch/test_url_and_discovery.py — this module
# covers tab *parsing*, badge annotation, and the Artist.tabs API surface.


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


class TestTabColumnVariants:
    """Real-world column variants from the 2026-07-18 review: Carti's
    Released tab uses Rel./Rec. Era, Travis Stems uses Title/Sources with
    no Era or Link(s) column."""

    CARTI_RELEASED_HTML = (
        "<table>"
        "<tr><td>Rel. Era</td><td>Rec. Era</td><td>Name</td><td>Notes</td>"
        "<td>Link(s)</td></tr>"
        "<tr><td>Die Lit</td><td>Self-Titled</td><td>R.I.P.</td><td>final</td>"
        "<td><a href='https://pillows.su/f/abc'>l</a></td></tr>"
        "</table>"
    )

    def test_dual_era_released_keeps_release_era(self):
        entries = parse_misc_tab(self.CARTI_RELEASED_HTML, "released")
        assert len(entries) == 1
        # Release era (first era-mapped column) wins for grouping
        assert entries[0].era_name == "Die Lit"
        assert entries[0].links == ["https://pillows.su/f/abc"]

    TRAVIS_STEMS_HTML = (
        "<table>"
        "<tr><td>Title</td><td>Notes</td><td>Leak Date</td><td>Sources</td></tr>"
        "<tr><td>Sky Stems</td><td>full stems</td><td>May 2023</td>"
        "<td><a href='https://pillows.su/f/xyz'>l</a></td></tr>"
        "</table>"
    )

    def test_stems_title_sources_no_era_parses(self):
        entries = parse_misc_tab(self.TRAVIS_STEMS_HTML, "stems")
        assert len(entries) == 1
        assert entries[0].name == "Sky Stems"
        assert entries[0].date == "May 2023"
        assert entries[0].links == ["https://pillows.su/f/xyz"]


class TestBatchedBadgeAnnotation:
    """2026-07-18 review fixes: one index build for all badge tabs, and
    placeholder tracks are never badge targets."""

    def test_batched_apply_badge_tabs_single_index(self):
        from src.parser import apply_badge_tabs
        artist = TestBadgeTabAnnotation._artist()
        entry = TestBadgeTabAnnotation._entry
        applied = apply_badge_tabs(artist, [
            ("best_of", [entry("Hurricane", era="Yeezus")]),
            ("worst_of", [entry("Jail")]),
        ])
        assert applied == 2
        yeezus_hurricane = next(
            s for s in artist.eras[1].sections[0].songs if s.base_name == "Hurricane"
        )
        assert yeezus_hurricane.versions[0].badge == "best"
        assert artist.eras[0].sections[0].songs[1].versions[0].badge == "worst"

    def test_placeholder_songs_never_badged(self):
        from src.models import Era, Section, Song, SongVersion
        from src.parser import apply_badge_tab
        artist = Artist(name="T", slug="t", eras=[
            Era(name="E", sections=[Section(songs=[
                Song(base_name="Untitled", versions=[SongVersion(name="Untitled")]),
            ])])
        ])
        entry = TestBadgeTabAnnotation._entry
        # A badge entry named "Untitled" must not stamp a placeholder track.
        assert apply_badge_tab(artist, "best_of", [entry("Untitled", era="E")]) == 0
