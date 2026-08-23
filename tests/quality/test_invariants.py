"""Run the structural invariants over every tracker we can reach.

Two tiers, deliberately:

* Synthetic fixtures are committed and run in CI. They are invented content
  (DMCA-safe) but exercise the real grammar, so CI gates on them.
* The captured corpus (`.cache/`) is real tracker HTML and is never committed.
  When it is present locally these same invariants run across every workbook,
  which is the only way to see failures on layouts nobody thought to invent.

Neither tier pins a number, so neither can be quietly re-pinned to hide a
regression — the thing that made the old `tests/accuracy` baselines unable to
tell a fix from a break.
"""

from __future__ import annotations

import glob
import json
import os
from collections.abc import Iterator

import pytest

from src.parser import parse_sheet
from tests.conftest import SYNTHETIC_DIR, read_synthetic
from tests.quality.invariants import violations

CORPUS_DIR = os.environ.get("LEAKSHEET_CORPUS", ".cache")

SYNTHETIC_TABS = sorted(p.stem for p in SYNTHETIC_DIR.glob("*.html"))


class TestSyntheticInvariants:
    """CI gate. Every committed fixture must parse to a structurally sound tree."""

    @pytest.mark.parametrize("name", SYNTHETIC_TABS)
    def test_fixture_parses_cleanly(self, name):
        artist = parse_sheet(read_synthetic(name), "SynthWave")
        assert violations(artist) == []

    def test_there_are_fixtures_to_run(self):
        # A glob that silently matches nothing would make this whole class pass
        # while testing nothing at all.
        assert len(SYNTHETIC_TABS) >= 8


def _corpus_paths() -> list[str]:
    """Cached tab paths worth parsing. Cheap: stats files, reads none."""
    if not os.path.isdir(CORPUS_DIR):
        return []
    out = []
    for path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.html"))):
        try:
            if 20_000 < os.path.getsize(path) < 4_000_000:
                out.append(path)
        except OSError:
            continue
    return out


def corpus_tabs() -> "Iterator[tuple[str, str, str]]":
    """Yield (html, title, url) one tab at a time.

    A generator, not a list, and called lazily rather than at import. Building
    the list at module scope read 757 MB of HTML into memory and pushed peak
    RSS to 1.9 GB — on every bare `pytest` run, because collection imports this
    module even though the marker deselects every test that needs the corpus.
    Streaming also means the raw HTML is never all resident at once; only the
    parsed models in `parsed_corpus` are kept.
    """
    for path in _corpus_paths():
        meta_path = path.replace(".html", ".meta.json")
        title, url = "?", ""
        if os.path.exists(meta_path):
            try:
                meta = json.load(open(meta_path))
                title, url = meta.get("title", "?"), meta.get("url", "")
            except (OSError, ValueError):
                pass
        try:
            yield open(path, encoding="utf-8", errors="replace").read(), title, url
        except OSError:
            continue


# Presence check only — stats the directory, never opens a file, so the
# skipif can be evaluated at collection time without the memory cost.
corpus_required = pytest.mark.skipif(
    not _corpus_paths(),
    reason=f"no captured corpus at {CORPUS_DIR} (real tracker HTML is never committed)",
)

# Parsing the whole corpus takes minutes, so do it once and share it rather
# than once per test.
_PARSED: "list[tuple[str, object]] | None" = None


def parsed_corpus() -> "list[tuple[str, object]]":
    """(title, Artist) for every cached tab that parses. Cached across tests."""
    global _PARSED
    if _PARSED is None:
        out = []
        for html, title, url in corpus_tabs():
            try:
                out.append((title, parse_sheet(html, title, url or None)))
            except Exception:  # noqa: BLE001 - test_parsing_never_raises reports these
                continue
        _PARSED = out
    return _PARSED


@pytest.mark.accuracy
@corpus_required
class TestCorpusInvariants:
    """Real trackers. Marked `accuracy` so it stays out of the offline gate."""

    def test_no_relative_art_urls_anywhere(self):
        """Cover art must be fetchable. 268 eras carried an unfetchable
        "/assets/<sha>.jpg" before the URL was resolved against its tab."""
        bad = [
            f"{title}: {era.name} -> {era.art_url}"
            for title, artist in parsed_corpus()
            for era in artist.eras
            if era.art_url and era.art_url.startswith("/")
        ]
        assert bad == [], f"{len(bad)} relative art URLs, e.g. {bad[:3]}"

    def test_row_accounting_holds_on_every_tracker(self):
        from tests.quality.invariants import check_row_accounting
        bad = [
            f"{title}: {v}"
            for title, artist in parsed_corpus()
            for v in check_row_accounting(artist)
        ]
        assert bad == [], f"{len(bad)} row-accounting failures, e.g. {bad[:3]}"

    def test_no_duplicate_era_names(self):
        """Era.id is the era name on iOS, so a duplicate makes SwiftUI drop a row."""
        bad = []
        for title, artist in parsed_corpus():
            names = [e.name for e in artist.eras]
            if len(names) != len(set(names)):
                dupes = {n for n in names if names.count(n) > 1}
                bad.append(f"{title}: {sorted(dupes)[:3]}")
        assert bad == [], f"{len(bad)} trackers with duplicate era names, e.g. {bad[:3]}"

    def test_ratings_are_within_range(self):
        from tests.quality.invariants import check_field_sanity
        bad = [
            f"{title}: {v}"
            for title, artist in parsed_corpus()
            for v in check_field_sanity(artist)
            if "rating" in v
        ]
        assert bad == [], f"{len(bad)} rating violations, e.g. {bad[:3]}"

    def test_parsing_never_raises(self):
        """A crash on one tracker is a 500 for that user."""
        bad = []
        for html, title, url in corpus_tabs():
            try:
                parse_sheet(html, title, url or None)
            except Exception as exc:  # noqa: BLE001 - the point of the test
                bad.append(f"{title}: {type(exc).__name__}: {exc}")
        assert bad == [], f"{len(bad)} trackers raised, e.g. {bad[:3]}"
