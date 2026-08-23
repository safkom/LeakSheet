"""Hand-labelled ground truth for one tracker per layout family.

Everything else in this suite checks that a parse is *internally consistent*.
Nothing there can catch the parser being confidently, consistently wrong — a
mislabelled column is perfectly self-consistent. Only values a human read off
the rendered sheet can.

The labels in `labels/*.json` contain no tracker content beyond era and song
names needed to identify a row: no links, no notes, no file names. The HTML
itself is never committed (DMCA — see .gitignore); each label records the
sha256 of the tab it was read from, and the test hydrates that tab out of the
local cache. Absent cache means skip, never silent pass.

To add a tracker: `python3 -m tests.quality.make_label <url-substring>` writes
a draft from current parser output, then VERIFY EVERY VALUE against the real
sheet before committing it. A draft accepted unread is just another
self-referential baseline, which is the exact failure this suite replaces.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
from pathlib import Path

import pytest

from src.parser import parse_sheet

LABELS_DIR = Path(__file__).parent / "labels"
CORPUS_DIR = os.environ.get("LEAKSHEET_CORPUS", ".cache")

LABEL_FILES = sorted(LABELS_DIR.glob("*.json")) if LABELS_DIR.is_dir() else []


def _load_labels() -> list[dict]:
    out = []
    for path in LABEL_FILES:
        with open(path) as fh:
            data = json.load(fh)
        data["_file"] = path.name
        out.append(data)
    return out


LABELS = _load_labels()


def _candidate_paths() -> list[str]:
    """Every local copy of tracker HTML, from either untracked store."""
    return (
        glob.glob(os.path.join(CORPUS_DIR, "*.html"))
        + glob.glob(os.path.join("Trackers", "*_files", "sheet.html"))
    )


def _tab_by_sha(sha: str) -> str | None:
    """Find the local tab whose bytes hash to *sha*."""
    for path in _candidate_paths():
        try:
            raw = open(path, "rb").read()
        except OSError:
            continue
        if hashlib.sha256(raw).hexdigest() == sha:
            return raw.decode("utf-8", errors="replace")
    return None


def _parse(label: dict):
    html = _tab_by_sha(label["sha256"])
    if html is None:
        pytest.skip(
            f"{label['_file']}: no cached tab with sha256 {label['sha256'][:12]}… "
            f"in {CORPUS_DIR} (real tracker HTML is never committed)"
        )
    return parse_sheet(html, label["artist"], label["source_url"])


# pytest wants a list of ids matching the params, not a callable over the list.
LABEL_IDS = [lb["_file"] for lb in LABELS]


@pytest.mark.accuracy
@pytest.mark.skipif(not LABELS, reason="no label files in tests/quality/labels/")
class TestLabelledTrackers:

    @pytest.mark.parametrize("label", LABELS, ids=LABEL_IDS)
    def test_era_names_and_order(self, label):
        artist = _parse(label)
        expected = [e["name"] for e in label["eras"]]
        assert [e.name for e in artist.eras] == expected

    @pytest.mark.parametrize("label", LABELS, ids=LABEL_IDS)
    def test_song_counts_per_era(self, label):
        artist = _parse(label)
        actual = {
            e.name: sum(len(s.songs) for s in e.sections) for e in artist.eras
        }
        expected = {e["name"]: e["songs"] for e in label["eras"]}
        assert actual == expected

    @pytest.mark.parametrize("label", LABELS, ids=LABEL_IDS)
    def test_era_art_presence(self, label):
        artist = _parse(label)
        actual = {e.name: bool(e.art_url) for e in artist.eras}
        expected = {e["name"]: e["has_art"] for e in label["eras"]}
        assert actual == expected

    @pytest.mark.parametrize("label", LABELS, ids=LABEL_IDS)
    def test_spot_checked_field_values(self, label):
        """Individual values read off the rendered sheet by hand."""
        artist = _parse(label)
        failures = []
        for check in label.get("spot_checks", []):
            version = _find_version(
                artist, check["era"], check["song"], check.get("version_tag")
            )
            if version is None:
                failures.append(f"{check['era']} / {check['song']}: not found")
                continue
            actual = getattr(version, check["field"], None)
            if actual != check["expect"]:
                failures.append(
                    f"{check['song']}.{check['field']}: "
                    f"{actual!r} != expected {check['expect']!r}"
                )
        assert failures == [], "\n".join(failures)

    @pytest.mark.parametrize("label", LABELS, ids=LABEL_IDS)
    def test_era_level_checks(self, label):
        """Era metadata read off the sheet: timeline dates, description presence."""
        artist = _parse(label)
        failures = []
        for check in label.get("era_checks", []):
            era = next((e for e in artist.eras if e.name == check["era"]), None)
            if era is None:
                failures.append(f"era {check['era']!r}: not found")
                continue
            if "timeline_first_date" in check:
                actual = era.timeline[0].date if era.timeline else None
                if actual != check["timeline_first_date"]:
                    failures.append(
                        f"{era.name}.timeline[0].date: {actual!r} != "
                        f"{check['timeline_first_date']!r}"
                    )
            if "min_timeline_events" in check:
                if len(era.timeline) < check["min_timeline_events"]:
                    failures.append(
                        f"{era.name}: {len(era.timeline)} timeline events, "
                        f"expected >= {check['min_timeline_events']}"
                    )
        assert failures == [], "\n".join(failures)


def _find_version(artist, era_name: str, song_name: str, version_tag=None):
    for era in artist.eras:
        if era.name != era_name:
            continue
        for section in era.sections:
            for song in section.songs:
                if song.base_name != song_name:
                    continue
                if version_tag is None:
                    return song.versions[0] if song.versions else None
                return next(
                    (v for v in song.versions if v.version_tag == version_tag), None
                )
    return None
