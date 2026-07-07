"""Accuracy harness over the live-tracker snapshots (tests/fixtures/snapshots/).

Mirror of test_fixture_accuracy.py for the 7 gzipped snapshots captured by
tests/tools/census.py on 2026-07-06. Baselines pin current parser behavior;
any change must be an intentional, explained improvement (update the baseline
in the same commit) or it is a regression.

Known deviations found during the 2026-07-06 census are allowlisted below
(KNOWN_*) so this harness is green on the pre-fix parser; fixes shrink the
allowlists in the same commit as the parser change.
"""

import gzip
from pathlib import Path

import pytest

from src.parser import _PLACEHOLDER_BASE_NAMES, parse_sheet

SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "snapshots"

# Pinned 2026-07-06 from the census run (pre-fix parser state).
BASELINES = {
    "yetracker": dict(
        eras=44, songs=3949, versions=9105,
        total_rows=9314, song_rows=9105, skipped=0, footer=115, other_rows=94,
        fuzzy=4, songs_with_10plus_versions=142,
    ),
    "tracker-1gJq": dict(  # Travis Scott
        eras=15, songs=1165, versions=1306,
        total_rows=1382, song_rows=1306, skipped=1, footer=0, other_rows=75,
        fuzzy=0, songs_with_10plus_versions=2,
    ),
    "tracker-1i4O": dict(
        eras=19, songs=735, versions=974,
        total_rows=1042, song_rows=974, skipped=0, footer=22, other_rows=46,
        fuzzy=0, songs_with_10plus_versions=1,
    ),
    "tracker-1v55": dict(
        eras=29, songs=793, versions=998,
        total_rows=1142, song_rows=998, skipped=0, footer=63, other_rows=81,
        fuzzy=0, songs_with_10plus_versions=4,
    ),
    "tracker-1_SN": dict(
        eras=6, songs=197, versions=286,
        total_rows=334, song_rows=286, skipped=0, footer=19, other_rows=29,
        fuzzy=0, songs_with_10plus_versions=2,
    ),
    "tracker-1zqq": dict(
        eras=30, songs=2225, versions=2459,
        total_rows=2674, song_rows=2459, skipped=0, footer=31, other_rows=184,
        fuzzy=0, songs_with_10plus_versions=1,
    ),
    "tracker-1Irt": dict(  # Playboi Carti [Official]
        eras=29, songs=1182, versions=1603,
        # skipped 2→0, other 212→214 (2026-07-06): the 'Full LQs' note-annotated
        # section label and a timeline continuation row are now classified as
        # structural rows instead of being dropped as unmatched.
        total_rows=1859, song_rows=1603, skipped=0, footer=42, other_rows=214,
        fuzzy=22, songs_with_10plus_versions=4,
    ),
}

# Deviations observed at pinning time — each is a live review finding; a fix
# removes the entry here in the same commit.
KNOWN_DROPPED_COLUMNS: dict[str, set[str]] = {}
KNOWN_EMPTY_ERAS = {
    # Verified 2026-07-06: the Drake sheet itself has an empty trailing
    # 'Unknown' era (all-zero stats, footer follows immediately). Parser is
    # faithful to the sheet — tracker content, not a defect.
    "tracker-1v55": {"unknown"},
}

MAX_SKIPPED_RATIO = 0.01


def _load(slug: str):
    path = SNAPSHOT_DIR / f"{slug}.html.gz"
    html = gzip.open(path, "rt", encoding="utf-8").read()
    return parse_sheet(html, slug)


@pytest.fixture(scope="module")
def parsed():
    return {slug: _load(slug) for slug in BASELINES}


def _all_songs(artist):
    for era in artist.eras:
        for sec in era.sections:
            for song in sec.songs:
                yield era, song


@pytest.mark.parametrize("name", sorted(BASELINES))
class TestSnapshotAccuracy:
    def test_row_accounting_identity(self, parsed, name):
        md = parsed[name].parse_metadata
        b = BASELINES[name]
        other = md.total_rows - md.song_rows - md.skipped_rows - md.footer_rows
        assert other >= 0
        assert md.total_rows == b["total_rows"]
        assert md.song_rows == b["song_rows"]
        assert md.footer_rows == b["footer"]
        assert other == b["other_rows"]

    def test_skipped_ratio(self, parsed, name):
        md = parsed[name].parse_metadata
        assert md.skipped_rows == BASELINES[name]["skipped"]
        assert md.skipped_rows <= md.total_rows * MAX_SKIPPED_RATIO
        assert md.unmatched_rows_total == md.skipped_rows

    def test_counts_pinned(self, parsed, name):
        a = parsed[name]
        b = BASELINES[name]
        assert len(a.eras) == b["eras"]
        assert a.total_songs == b["songs"]
        assert a.total_versions == b["versions"]

    def test_no_empty_eras(self, parsed, name):
        allowed = KNOWN_EMPTY_ERAS.get(name, set())
        empty = [
            e.name for e in parsed[name].eras
            if e.song_count == 0 and not e.description and not (e.timeline or [])
            and e.name.strip().lower() not in allowed
        ]
        assert empty == [], f"empty eras: {empty}"

    def test_fuzzy_matches_pinned(self, parsed, name):
        assert parsed[name].parse_metadata.fuzzy_matched_rows == BASELINES[name]["fuzzy"]

    def test_version_grouping_outliers_pinned(self, parsed, name):
        big = [s for _, s in _all_songs(parsed[name]) if len(s.versions) >= 10]
        assert len(big) == BASELINES[name]["songs_with_10plus_versions"]

    def test_no_placeholder_grouping(self, parsed, name):
        merged_wrongly = [
            (era.name, song.base_name, len(song.versions))
            for era, song in _all_songs(parsed[name])
            if song.base_name.lower() in _PLACEHOLDER_BASE_NAMES
            and len(song.versions) > 1
            and any(not (v.alt_titles or []) for v in song.versions)
        ]
        assert merged_wrongly == []

    def test_all_columns_mapped(self, parsed, name):
        allowed = KNOWN_DROPPED_COLUMNS.get(name, set())
        md = parsed[name].parse_metadata
        unknown = [c for c in md.dropped_columns if c.lower() not in allowed]
        assert unknown == [], f"unmapped header columns dropping data: {unknown}"


class TestCartiOfficialStructuralRows:
    """Two rows the 2026-07-06 census left unmatched on the official Carti
    tracker, verified against raw snapshot rows 898/1031:

    - 'Full LQs\\nnote: check the remasters tab…' is a section label with an
      attached note line; skipping it misfiled the following songs (Bitch
      Boy, Eastside, …) into the previous section.
    - '(December 25, 2020 - March, 2021) - Carti continues to record…' is a
      timeline continuation row under the 'Whole Lotta Red (Deluxe)' era
      header; skipping it dropped a timeline event.
    """

    def test_full_lqs_section_label_with_note(self, parsed):
        artist = parsed["tracker-1Irt"]
        era = next(e for e in artist.eras if e.name == "Whole Lotta Red [V2]")
        sec = next((s for s in era.sections if s.name == "Full LQs"), None)
        assert sec is not None, f"sections: {[s.name for s in era.sections]}"
        assert any("Bitch Boy" in song.base_name for song in sec.songs), (
            f"songs in 'Full LQs': {[s.base_name for s in sec.songs][:8]}"
        )

    def test_timeline_continuation_row_appended(self, parsed):
        artist = parsed["tracker-1Irt"]
        era = next(e for e in artist.eras if e.name == "Whole Lotta Red (Deluxe)")
        assert any(
            "continues to record" in ev.event for ev in era.timeline
        ), f"timeline: {[(ev.date, ev.event[:40]) for ev in era.timeline]}"

    def test_no_unmatched_rows_remain(self, parsed):
        assert parsed["tracker-1Irt"].parse_metadata.skipped_rows == 0


class TestTravisSources:
    """The Travis Scott tracker's 'Sources' column carries labeled evidence
    links ('First Mention (Screenshot)', 'Trailer (YouTube)') — 513 rows.
    Verified against the raw snapshot on 2026-07-06."""

    def test_sources_extracted_with_labels(self, parsed):
        artist = parsed["tracker-1gJq"]
        versions = [
            v for era in artist.eras for song in era.songs for v in song.versions
        ]
        with_sources = [v for v in versions if v.sources]
        assert len(with_sources) >= 400, (
            f"expected ~513 versions with sources, got {len(with_sources)}"
        )
        # Spot-check a known row: '$tay [Demo]' sources a YouTube trailer.
        stay = next(v for v in versions if v.name.startswith("$tay"))
        assert any(
            s.label == "Trailer (YouTube)" and "youtube.com" in s.url
            for s in stay.sources
        ), f"$tay sources: {[(s.label, s.url[:60]) for s in stay.sources]}"

    def test_source_urls_cleaned_of_google_redirects(self, parsed):
        artist = parsed["tracker-1gJq"]
        for era in artist.eras:
            for song in era.songs:
                for v in song.versions:
                    for s in v.sources:
                        assert not s.url.startswith("https://www.google.com/url"), (
                            f"unclean source url on {v.name!r}: {s.url[:80]}"
                        )
