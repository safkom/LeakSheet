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
from src.parser import ERA_STATS_PATTERN, parse_sheet
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
        assert ERA_STATS_PATTERN.search(cell)

    @pytest.mark.parametrize("text", [
        "2 Chainz",             # artist name, digit-leading
        "Barter 7",
        "1985",
        "3 Doors Down",
        "Some 3 word title",
        "\U0001f517 3 Total Links",  # global footer, not an era
    ])
    def test_not_mistaken_for_stats(self, text):
        assert not ERA_STATS_PATTERN.search(text)


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
