"""Era-stats vocabulary: both stat dialects must produce a real era header.

Trackers write the era-stats cell in one of two unrelated vocabularies. Only
the leak-status one was recognised, so discography-style era headers were not
headers at all: the era vanished, its cover art / timeline / description went
with it, and its songs were appended to whichever era came before.

Measured over 400 captured real tabs before this fix: 267 lost era headers
across 34 tabs (~9% of trackers). See tests/tools/corpus_sweep.py for the
aggregate harness that produced those numbers.
"""

from __future__ import annotations

import pytest

from src.models import parse_era_stats
from src.parser import ERA_STATS_PATTERN, era_stats_match, parse_sheet
from tests.conftest import read_synthetic


@pytest.fixture(scope="module")
def drift():
    return parse_sheet(read_synthetic("discography_stats"), "PixelDrift")


class TestDiscographyEraHeaders:
    def test_all_three_eras_are_found(self, drift):
        assert [e.name for e in drift.eras] == ["First Light", "Second Wind", "Third Rail"]

    def test_songs_route_to_their_own_era(self, drift):
        counts = {e.name: sum(len(s.songs) for s in e.sections) for e in drift.eras}
        assert counts == {"First Light": 3, "Second Wind": 1, "Third Rail": 1}

    def test_era_art_survives(self, drift):
        by_name = {e.name: e for e in drift.eras}
        assert by_name["First Light"].art_url.endswith("FIRSTLIGHT")
        assert by_name["Second Wind"].art_url.endswith("SECONDWIND")

    def test_timeline_survives(self, drift):
        first = drift.eras[0]
        assert first.timeline and first.timeline[0].date == "2019"

    def test_stated_total_is_trusted_over_derivation(self, drift):
        by_name = {e.name: e for e in drift.eras}
        # Discography blocks populate no leak-status field, so deriving would
        # give 0. The sheet states the number outright; use it.
        assert by_name["First Light"].stats.stated_total == 3
        assert by_name["First Light"].stats.total == 3
        assert by_name["Second Wind"].stats.total == 2

    def test_release_types_keep_the_sheets_own_wording(self, drift):
        by_name = {e.name: e for e in drift.eras}
        assert by_name["First Light"].stats.release_types == {"single": 1, "album track": 2}
        assert by_name["Second Wind"].stats.release_types == {"feature": 1, "remix": 1}

    def test_leak_status_eras_still_derive_their_total(self, drift):
        third = next(e for e in drift.eras if e.name == "Third Rail")
        assert third.stats.stated_total == 0
        assert third.stats.total == 1
        assert third.stats.release_types == {}

    def test_footer_is_not_an_era(self, drift):
        # "3 Total Links" is the global footer. If the bare "Total" alternative
        # matches it, every sheet grows a phantom era at the bottom.
        assert not any("Total Links" in e.name for e in drift.eras)
        assert drift.parse_metadata.footer_rows == 1


class TestVocabularyBoundaries:
    @pytest.mark.parametrize("cell", [
        "18 Total\n4 Single / Album Track(s)\n7 Album Track(s)\n2 Feature",
        "0 Album Track\n0 Single\n0 Feature\n0 Production\n2 Other",
        "8 Total\n1 Single / Album Track\n3 Album Track\n1 OST Track\n3 Remix",
        "17 Total\n5 Acapella(s)\n12 Instrumental(s)",
        "11 Total\n6 Single\n3 Feature\n2 EP Track",
        "1 OG File\n45 Full\n1 Tagged\n3 Partial\n4 Snippet(s)\n70 Unavailable",
    ])
    def test_recognised(self, cell):
        assert era_stats_match(cell)

    @pytest.mark.parametrize("text", [
        "2 Chainz",             # artist name, digit-leading
        "Barter 7",
        "1985",
        "3 Doors Down",
        "Some 3 word title",
        "\U0001f517 3 Total Links",  # global footer, not an era
        # Era NAMES built from the discography vocabulary. Matching any of
        # these on a single pair turned 86 Bonnie McKee song rows into empty
        # eras, because every one of those rows carried the era name
        # "2009 Album" in its Era column.
        "2009 Album",
        "1977 Sessions",
        "38 Special Sessions",
        "2020 Throwaways",
        "2019 Loosies",
        "2015 Demos",
        "3 Originals",
    ])
    def test_not_mistaken_for_stats(self, text):
        assert not era_stats_match(text)

    @pytest.mark.parametrize("cell", [
        "18 Total\n4 Singles",
        "2009 Album\n5 Singles\n3 Album Tracks",
    ])
    def test_discography_needs_two_pairs(self, cell):
        # One pair of discography vocabulary is an era name; two or more is a
        # stats block. Leak-status vocabulary is exempt — "5 Full" alone is
        # never anything but a stats cell.
        assert era_stats_match(cell)

    def test_single_leak_status_pair_still_matches(self):
        assert era_stats_match("5 Full")


class TestReleaseTypeRouting:
    def test_leak_status_labels_do_not_leak_into_release_types(self):
        stats = parse_era_stats("1 OG File\n45 Full\n3 Partial\n4 Snippet(s)\n70 Unavailable")
        assert stats.release_types == {}
        assert (stats.og_files, stats.full, stats.partial) == (1, 45, 3)

    def test_unknown_labels_are_preserved_not_dropped(self):
        # An exact-key map silently turns unlisted wording into 0. Keeping the
        # label means a tracker inventing new vocabulary still shows its counts.
        stats = parse_era_stats("4 Loosies\n2 Throwaways\n1 Skit(s)")
        assert stats.release_types == {"loosies": 4, "throwaways": 2, "skit": 1}


class TestMiscEraHeaderRows:
    """An era header on a Misc tab must not become an entry.

    Some Misc tabs put the era DESCRIPTION in the column that maps to `date`.
    That made the header row look like it carried track data, so the
    era-header guard never fired and the era was emitted as an entry whose
    "date" was a paragraph of prose — 37 of them on the Ye tracker's Misc tab,
    each rendering a wall of text beside a calendar icon in the app.
    """

    MISC_TAB = """
    <html><body><table>
    <tr><td>Era</td><td>Name</td><td>Notes</td><td>Leak Date</td>
        <td>Type</td><td>Link(s)</td></tr>
    <tr><td></td><td>Opening Era</td><td>(2019) (it begins)</td>
        <td>A long paragraph about the era that is definitely not a date and
            runs well past any plausible date length.</td>
        <td></td><td></td></tr>
    <tr><td>Opening Era</td><td>Real Entry</td><td>note</td>
        <td>Jul 15, 2024</td><td>Music Video</td>
        <td><a href="https://youtube.com/watch?v=abc">watch</a></td></tr>
    </table></body></html>
    """

    def test_era_header_row_is_not_an_entry(self):
        from src.parser import parse_misc_tab
        entries = parse_misc_tab(self.MISC_TAB, "misc", ["Opening Era"])
        assert [e.name for e in entries] == ["Real Entry"]

    def test_real_dates_survive(self):
        from src.parser import parse_misc_tab
        entry = parse_misc_tab(self.MISC_TAB, "misc", ["Opening Era"])[0]
        assert entry.date == "Jul 15, 2024"
        assert entry.entry_type == "Music Video"

    def test_prose_never_reaches_the_date_field(self):
        from src.parser import parse_misc_tab
        for e in parse_misc_tab(self.MISC_TAB, "misc", ["Opening Era"]):
            assert e.date is None or len(e.date) <= 40
