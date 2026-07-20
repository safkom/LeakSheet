"""Accuracy verification harness — reconciles parsed output against the raw
sheets for every local tracker fixture.

Pinned baselines make silent parser drift loud: any change that shifts era,
song, or row-classification counts on a fixture fails here and must either be
an intentional improvement (update the baseline in the same commit, with a
rationale) or a regression.

Run with LEAKSHEET_ACCURACY_VERBOSE=1 to dump unmatched rows, dropped
columns, and suspicious groupings for triage:

    LEAKSHEET_ACCURACY_VERBOSE=1 python3 -m pytest tests/test_fixture_accuracy.py -s
"""

import os

import pytest

from src.config import discover_trackers
from src.parser import parse_file

VERBOSE = os.environ.get("LEAKSHEET_ACCURACY_VERBOSE") == "1"

# ---------------------------------------------------------------------------
# Pinned baselines (recorded 2026-07-05, after the placeholder-grouping fix).
#
# `other_rows` = era headers + section labels + pre-footer decorations —
# rows that are neither songs, skips, nor footer. It completes the row
# accounting identity: song + skipped + footer + other == total.
# ---------------------------------------------------------------------------
BASELINES = {
    "Baby Keem": dict(
        eras=6, songs=187, versions=271,
        total_rows=316, song_rows=271, skipped=0, footer=20, other_rows=25,
        fuzzy=0, songs_with_10plus_versions=2,
    ),
    "Kendrick Lamar": dict(
        eras=19, songs=668, versions=863,
        total_rows=931, song_rows=863, skipped=1, footer=23, other_rows=44,
        fuzzy=0, songs_with_10plus_versions=1,
    ),
    "Playboi Carti": dict(
        eras=28, songs=1004, versions=1367,
        total_rows=1561, song_rows=1367, skipped=0, footer=22, other_rows=172,
        fuzzy=13, songs_with_10plus_versions=4,
    ),
    "Ye": dict(
        eras=42, songs=3586, versions=8105,
        total_rows=8299, song_rows=8105, skipped=0, footer=108, other_rows=86,
        fuzzy=5, songs_with_10plus_versions=123,
    ),
}

# Header cells that intentionally map to no field (decorative/meta columns).
KNOWN_IGNORED_COLUMNS: set[str] = set()

# Maximum share of data rows a parser may skip before we call it data loss.
MAX_SKIPPED_RATIO = 0.01


# Opt-in: needs the gitignored Trackers/ dumps. Skipped on a clean checkout / CI.
pytestmark = [
    pytest.mark.accuracy,
    pytest.mark.skipif(
        not set(BASELINES) <= {n for n, _ in discover_trackers()},
        reason="local Trackers/ dumps not present (gitignored; run -m accuracy locally)",
    ),
]


@pytest.fixture(scope="module")
def parsed():
    results = {}
    for artist_name, sheet_path in discover_trackers():
        if artist_name in BASELINES:
            results[artist_name] = parse_file(sheet_path, artist_name)
    return results


def _all_songs(artist):
    for era in artist.eras:
        for sec in era.sections:
            for song in sec.songs:
                yield era, song


@pytest.mark.parametrize("name", sorted(BASELINES))
class TestFixtureAccuracy:
    def test_row_accounting_identity(self, parsed, name):
        """No row may silently vanish: every non-header row is a song, a skip,
        a footer, or a structural (era/section) row."""
        md = parsed[name].parse_metadata
        b = BASELINES[name]
        other = md.total_rows - md.song_rows - md.skipped_rows - md.footer_rows
        assert other >= 0, "negative structural-row count — classification double-counts"
        assert md.total_rows == b["total_rows"], f"total_rows {md.total_rows} != pinned {b['total_rows']}"
        assert md.song_rows == b["song_rows"], f"song_rows {md.song_rows} != pinned {b['song_rows']}"
        assert md.footer_rows == b["footer"], f"footer_rows {md.footer_rows} != pinned {b['footer']}"
        assert other == b["other_rows"], f"structural rows {other} != pinned {b['other_rows']}"

    def test_skipped_ratio(self, parsed, name):
        md = parsed[name].parse_metadata
        b = BASELINES[name]
        assert md.skipped_rows == b["skipped"], f"skipped {md.skipped_rows} != pinned {b['skipped']}"
        assert md.skipped_rows <= md.total_rows * MAX_SKIPPED_RATIO
        assert md.unmatched_rows_total == md.skipped_rows, "unmatched counter out of sync with skips"
        if VERBOSE and md.unmatched_rows:
            print(f"\n[{name}] unmatched rows:")
            for row in md.unmatched_rows:
                print("  ", row[:160])

    def test_counts_pinned(self, parsed, name):
        a = parsed[name]
        b = BASELINES[name]
        assert len(a.eras) == b["eras"], f"eras {len(a.eras)} != pinned {b['eras']}"
        assert a.total_songs == b["songs"], f"songs {a.total_songs} != pinned {b['songs']}"
        assert a.total_versions == b["versions"], f"versions {a.total_versions} != pinned {b['versions']}"

    def test_no_empty_eras(self, parsed, name):
        """An era with no songs AND no description captured nothing — a header
        was recognized but its content lost."""
        empty = [
            e.name for e in parsed[name].eras
            if e.song_count == 0 and not e.description and not (e.timeline or [])
        ]
        assert empty == [], f"empty eras: {empty}"

    def test_fuzzy_matches_pinned(self, parsed, name):
        md = parsed[name].parse_metadata
        assert md.fuzzy_matched_rows == BASELINES[name]["fuzzy"], (
            f"fuzzy matches {md.fuzzy_matched_rows} != pinned {BASELINES[name]['fuzzy']} — "
            "verify new fuzzy matches are correct before repinning"
        )

    def test_version_grouping_outliers_pinned(self, parsed, name):
        """Songs with ≥10 versions are legitimate in these trackers, but a jump
        means base-name grouping started over-merging."""
        big = [
            (song.base_name, len(song.versions), era.name)
            for era, song in _all_songs(parsed[name])
            if len(song.versions) >= 10
        ]
        if VERBOSE and big:
            print(f"\n[{name}] songs with ≥10 versions:")
            for base, n, era_name in sorted(big, key=lambda x: -x[1])[:10]:
                print(f"   {n:3d}× {base}  ({era_name})")
        assert len(big) == BASELINES[name]["songs_with_10plus_versions"]

    def test_no_placeholder_grouping(self, parsed, name):
        """'???' / 'Unknown' rows only group via shared fan-made alt titles
        (the song's de-facto identity). A grouped placeholder song must never
        contain an alt-title-less version — those are distinct mystery
        tracks and stay standalone."""
        from src.parser import _PLACEHOLDER_BASE_NAMES

        merged_wrongly = []
        for era, song in _all_songs(parsed[name]):
            if song.base_name.lower() not in _PLACEHOLDER_BASE_NAMES or len(song.versions) <= 1:
                continue
            if any(not (v.alt_titles or []) for v in song.versions):
                merged_wrongly.append((era.name, song.base_name, len(song.versions)))
        assert merged_wrongly == [], f"placeholder songs wrongly grouped: {merged_wrongly}"

    def test_no_duplicate_era_names(self, parsed, name):
        from collections import Counter

        counts = Counter(e.name.strip().lower() for e in parsed[name].eras)
        dupes = [k for k, c in counts.items() if c > 1]
        assert dupes == [], f"duplicate era names (mis-split headers?): {dupes}"

    def test_all_columns_mapped(self, parsed, name):
        """Every non-empty header cell maps to a field or is explicitly
        known-ignored — unknown columns must not silently drop data."""
        md = parsed[name].parse_metadata
        unknown = [c for c in md.dropped_columns if c.lower() not in KNOWN_IGNORED_COLUMNS]
        if VERBOSE and unknown:
            print(f"\n[{name}] dropped columns: {unknown}")
        assert unknown == [], f"unmapped header columns dropping data: {unknown}"
