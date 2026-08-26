"""Aggregate parser-quality sweep over a corpus of captured tracker HTML.

This replaces the per-tracker baseline dicts in the old ``tests/accuracy``
harness. Those pinned the parser's own output as its own expectation, so a
regression and an improvement looked identical: both were "a delta to triage".

This tool measures *aggregate* quality signals instead — coverage ratios, junk
counts, invariant violations — over every tab in the corpus. Aggregates move
monotonically when the parser genuinely improves, so a baseline comparison is
meaningful without anyone hand-verifying hundreds of numbers.

The corpus is captured tracker HTML, which is never committed (DMCA — see
.gitignore). Point ``--corpus`` at a local ``.cache`` directory.

    python3 -m tests.tools.corpus_sweep --report
    python3 -m tests.tools.corpus_sweep --out before.json
    python3 -m tests.tools.corpus_sweep --baseline before.json
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.parser import era_stats_match, extract_table, parse_sheet  # noqa: E402

# Version fields whose population rate we track. A field being rare is not
# automatically a bug — some columns genuinely do not exist on most trackers —
# but a rate that *drops* between runs always is.
VERSION_FIELDS = (
    "version_tag", "badge", "featuring", "producers", "credited_artists",
    "notes", "og_filename", "track_length", "file_date", "leak_date",
    "available_length", "quality", "streaming", "rating", "date_of_recording",
    "type", "samples", "sources", "links", "alt_titles",
)

# A cell that looks like "<int> <words>" on most of its lines is an era stats
# block, whatever vocabulary it uses. Used to count era headers the parser
# fails to recognise.
_STATS_LINE_RE = re.compile(r"^\s*(\d+)\s+([A-Za-z][A-Za-z()/ .\-]{1,40})\s*$")

# Song names that are certainly not song names.
#
# A bare number is NOT one of them, though it reads like the archetypal
# track-number-column bug. Measured over the corpus, the rule fired 427 times
# and almost every hit was a real title: Tyler's "911" and "435", Ye's "530",
# Bon Iver's "1867", KAYTRANADA's "2013". A metric that is 90% false cannot be
# watched, so it was never going to catch the real thing it was aimed at.
_JUNK_NAME_RES = (
    re.compile(r"^https?://", re.IGNORECASE),         # bare URL
    re.compile(r"^#(REF|N/A|VALUE|DIV/0|NAME|NULL|NUM|ERROR)", re.IGNORECASE),
)

# Header and glossary rows emitted as songs — the defect that WAS buried inside
# the old bad-track-length count. A song whose track_length is the literal
# column header means the header row was parsed as data.
_HEADER_LEAK_VALUES = frozenset({
    "track length", "length of the song", "duration", "track duration",
})
# Google Sheets' epoch zero. A duration cell formatted as a date renders as
# this, so it is a formatting artifact rather than content.
_SHEETS_EPOCH_ZERO = "dec 30, 1899"

_TIME_RE = re.compile(r"^\d{1,3}:[0-5?]\d(:[0-5]\d)?$")
# Trackers write these for "we don't know how long it is". They are content,
# not parse failures — the same allowance tests/quality/invariants.py makes.
# Without it the metric counted 15,201 values, ~99% of them legitimate.
_UNKNOWN_TIME = re.compile(
    r"^(n/?a|\?+:?\?*|-|—|\.|x|tba|tbd|unknown|info needed)$", re.IGNORECASE
)
# Annotations trackers hang off a duration: "~2:00" approximate, "2:44*" and
# "2:00+" flagged, ">10:00" bounded, and a second line naming the take
# ("03:12\n(Open Vrs)"). None of them change whether the cell parsed correctly.
_DURATION_ANNOTATION = re.compile(r"^[~>< ]+|[*+ ]+$")


def _duration_core(value: str) -> str:
    """The duration itself, with tracker annotations stripped."""
    return _DURATION_ANNOTATION.sub("", value.split("\n")[0].strip())


_STAR_RE = re.compile(r"[⭐★☆️]")


@dataclass
class Totals:
    tabs: int = 0
    tabs_failed: int = 0
    eras: int = 0
    eras_with_art: int = 0
    eras_zero_song: int = 0
    eras_starved: int = 0
    songs: int = 0
    versions: int = 0
    rows: int = 0
    rows_skipped: int = 0
    rows_fuzzy: int = 0
    # quality defects
    art_relative: int = 0
    unmatched_stats_headers: int = 0
    tabs_with_unmatched_stats: int = 0
    junk_song_names: int = 0
    bad_track_length: int = 0
    header_rows_as_songs: int = 0
    bad_rating: int = 0
    stars_left_in_availability: int = 0
    era_stats_shortfall: int = 0
    field_hits: collections.Counter = field(default_factory=collections.Counter)
    art_hosts: collections.Counter = field(default_factory=collections.Counter)
    dropped_columns: collections.Counter = field(default_factory=collections.Counter)
    duplicate_columns: collections.Counter = field(default_factory=collections.Counter)
    unmatched_stat_labels: collections.Counter = field(default_factory=collections.Counter)
    detail: dict = field(default_factory=dict)


def _count_unmatched_stats_headers(rows) -> tuple[int, collections.Counter]:
    """Era-header-shaped rows whose stats cell the parser rejects.

    A multi-line first cell where most lines read "<int> <words>" is an era
    stats block by construction. If the production pattern does not match it,
    the whole era header — name, cover art, timeline, description — is lost.
    """
    misses = 0
    labels: collections.Counter = collections.Counter()
    for row in rows:
        if not row:
            continue
        cell = row[0].text.strip()
        if not cell or "\n" not in cell:
            continue
        lines = [ln for ln in cell.split("\n") if ln.strip()]
        matches = [_STATS_LINE_RE.match(ln) for ln in lines]
        hits = sum(1 for m in matches if m)
        if hits < max(2, len(lines) - 1):
            continue
        # Must mirror _is_era_header exactly, or the count measures the sweep's
        # own rule instead of the parser's.
        if era_stats_match(cell):
            continue
        misses += 1
        for m in matches:
            if m:
                labels[m.group(2).strip()] += 1
    return misses, labels


def sweep_tab(html: str, title: str, t: Totals, url: str = "") -> None:
    rows = extract_table(html)
    # Pass the URL: production does, and without it relative-art
    # resolution is never exercised, so the metric measures nothing.
    artist = parse_sheet(html, title, url or None)
    # Keyed by URL, never by title: 353 of 412 titles in a real cache cover
    # more than one tab (one title spans 26), so a title-keyed map silently
    # overwrites and a before/after diff then compares two different tabs.
    # That is exactly how a "lost 765 songs" reading was once produced from
    # two unrelated files. The title rides along in the value for readability.
    t.detail[url or title] = {
        "title": title,
        "eras": len(artist.eras),
        "eras_with_art": sum(1 for e in artist.eras if e.art_url),
        "songs": artist.total_songs,
        "leak_dates": sum(1 for e in artist.eras for s in e.sections for so in s.songs
                          for v in so.versions if v.leak_date),
    }

    t.tabs += 1
    misses, labels = _count_unmatched_stats_headers(rows)
    if misses:
        t.tabs_with_unmatched_stats += 1
        t.unmatched_stats_headers += misses
        t.unmatched_stat_labels.update(labels)

    # parse_sheet's empty-rows and non-song-tab early returns can leave this
    # unset; dereferencing it unguarded was the whole of `defect_tabs_failed`.
    md = artist.parse_metadata
    if md is not None:
        t.rows += md.total_rows
        t.rows_skipped += md.skipped_rows
        t.rows_fuzzy += md.fuzzy_matched_rows
        t.dropped_columns.update(md.dropped_columns)
        t.duplicate_columns.update(md.duplicate_columns)

    for era in artist.eras:
        t.eras += 1
        if era.art_url:
            t.eras_with_art += 1
            host = urlparse(era.art_url).netloc
            t.art_hosts[host or "<relative>"] += 1
            if not host:
                t.art_relative += 1

        era_songs = sum(len(s.songs) for s in era.sections)
        # The sheet's own stats block is maintainer-written ground truth. It
        # counts VERSIONS — one line per link — not songs, so this has to be
        # compared against the version count. Comparing songs reported 15,250
        # missing where 2,261 were actually missing: 85% of the metric was the
        # ordinary fact that a song has more than one version.
        era_versions = sum(len(so.versions) for s in era.sections for so in s.songs)
        claimed = era.stats.total if era.stats else 0
        if not era_songs:
            t.eras_zero_song += 1
            # An era that is empty AND claims nothing is empty in the source
            # (placeholder/future eras are common). Only an era that claims
            # songs and yielded none is a parser defect — measure that, or
            # every newly-detected empty era reads as a regression.
            if claimed:
                t.eras_starved += 1
        if claimed and era_versions < claimed:
            t.era_stats_shortfall += claimed - era_versions

        for section in era.sections:
            for song in section.songs:
                t.songs += 1
                if any(r.match(song.base_name) for r in _JUNK_NAME_RES):
                    t.junk_song_names += 1
                for v in song.versions:
                    t.versions += 1
                    for f in VERSION_FIELDS:
                        val = getattr(v, f, None)
                        if val not in (None, "", [], False):
                            t.field_hits[f] += 1
                    if v.track_length:
                        tl = v.track_length.strip()
                        low = tl.lower()
                        if low in _HEADER_LEAK_VALUES or low == _SHEETS_EPOCH_ZERO:
                            t.header_rows_as_songs += 1
                        else:
                            core = _duration_core(tl)
                            if not _TIME_RE.match(core) and not _UNKNOWN_TIME.match(core):
                                t.bad_track_length += 1
                    if v.rating is not None and not 1 <= v.rating <= 5:
                        t.bad_rating += 1
                    if v.available_length and _STAR_RE.search(v.available_length):
                        t.stars_left_in_availability += 1


_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


def _sheet_id(url: str) -> str:
    """Group key: the workbook a tab belongs to.

    Google tabs share a spreadsheet id, so they group on their own. Self-hosted
    trackers serve each tab from its own path — "/preview/sheet/937104017.html"
    — so keying on host+path made every tab its own "workbook": 24 for
    tylertracker.net alone. The sweep then scored 24 sub-tabs as 24 trackers,
    counting 318 art-less sub-tab eras against a corpus-wide art ratio that only
    a main tab can satisfy. One tracker per host is what production serves.
    """
    m = _SHEET_ID_RE.search(url or "")
    if m:
        return m.group(1)
    return urlparse(url or "").netloc or "<unknown>"


def _load(path: str) -> tuple[str, str, str]:
    """Return (html, title, url) for a cached tab."""
    meta_path = path.replace(".html", ".meta.json")
    title, url = "?", ""
    if os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path))
            title, url = meta.get("title", "?"), meta.get("url", "")
        except (OSError, ValueError):
            pass
    return open(path, encoding="utf-8", errors="replace").read(), title, url


def collect(
    corpus: str, limit: int, min_size: int, max_size: int, *, per_sheet: bool = True
) -> Totals:
    """Sweep the corpus.

    ``per_sheet`` mirrors production: a workbook has many tabs, and the fetcher
    parses exactly one of them as the song tab (scoring by era and song count).
    Sweeping every cached tab instead counts badge sub-tabs, glossaries and
    artwork indexes as if each were a tracker, which drags every ratio toward
    whatever those tabs happen to contain — era cover-art coverage especially,
    since only a main tab carries covers. Off by default only for debugging.
    """
    t = Totals()
    files = sorted(
        h for h in glob.glob(os.path.join(corpus, "*.html"))
        if min_size < os.path.getsize(h) < max_size
    )

    if per_sheet:
        # --limit must cut whole workbooks, never the flat tab list: cache
        # filenames are URL hashes, so an alphabetical slice splits workbooks
        # and can drop exactly the main tab a workbook is scored on.
        by_sheet: dict[str, list[str]] = {}
        for path in files:
            try:
                _, _, url = _load(path)
            except OSError:
                t.tabs_failed += 1
                continue
            by_sheet.setdefault(_sheet_id(url), []).append(path)
        keys = sorted(by_sheet)[:limit] if limit else sorted(by_sheet)

        # Same score tuple the fetcher uses to pick a workbook's main tab.
        selected = []
        for key in keys:
            best: tuple[tuple[int, int, int], str, str] | None = None
            for path in by_sheet[key]:
                try:
                    html, title, _url = _load(path)
                    artist = parse_sheet(html, title, _url or None)
                except Exception:  # noqa: BLE001
                    t.tabs_failed += 1
                    continue
                # Must stay identical to the fetcher's score tuple, or the
                # sweep measures a tab production would never have served.
                score = (1 if artist.total_songs else 0, artist.total_songs, len(artist.eras))
                if best is None or score > best[0]:
                    best = (score, html, title, _url)
            if best is not None:
                selected.append((best[1], best[2], best[3]))
    else:
        selected = []
        for path in (files[:limit] if limit else files):
            try:
                html, title, _url = _load(path)
            except OSError:
                t.tabs_failed += 1
                continue
            selected.append((html, title, _url))

    for html, title, url in selected:
        try:
            sweep_tab(html, title, t, url)
        except Exception:  # noqa: BLE001 - a crash is itself a measured defect
            t.tabs_failed += 1
    return t


def to_metrics(t: Totals) -> dict[str, Any]:
    """Flatten to the comparable scalar metrics. Higher is better unless the
    key starts with a defect prefix, which ``compare`` uses to pick direction."""
    pct = lambda n, d: round(100.0 * n / d, 2) if d else 0.0  # noqa: E731
    m: dict[str, Any] = {
        "tabs": t.tabs,
        "eras": t.eras,
        "songs": t.songs,
        "versions": t.versions,
        "pct_era_art": pct(t.eras_with_art, t.eras),
        "pct_era_zero_song": pct(t.eras_zero_song, t.eras),
        "defect_eras_starved": t.eras_starved,
        "pct_rows_skipped": pct(t.rows_skipped, t.rows),
        "defect_tabs_failed": t.tabs_failed,
        "defect_unmatched_stats_headers": t.unmatched_stats_headers,
        "defect_tabs_with_unmatched_stats": t.tabs_with_unmatched_stats,
        "defect_art_relative": t.art_relative,
        "defect_junk_song_names": t.junk_song_names,
        "defect_bad_track_length": t.bad_track_length,
        "defect_header_rows_as_songs": t.header_rows_as_songs,
        "defect_bad_rating": t.bad_rating,
        "defect_stars_in_availability": t.stars_left_in_availability,
        "defect_era_stats_shortfall": t.era_stats_shortfall,
    }
    for f in VERSION_FIELDS:
        m[f"pct_field_{f}"] = pct(t.field_hits[f], t.versions)
    return m


# Percentages where a DROP is the improvement. Everything else named pct_* is
# coverage, where a drop is the regression.
_LOWER_IS_BETTER = frozenset({"pct_rows_skipped"})

# Corpus-shape metrics. They move whenever the parser reclassifies rows (a row
# that was a song becoming an era header is a fix, not a loss), so they are
# reported but never scored.
#
# pct_era_zero_song belongs here too: better era detection surfaces eras that
# are genuinely empty in the source (placeholder and future eras are common),
# which pushes the ratio up while the parser got strictly better. The scored
# signal is defect_eras_starved — empty eras whose OWN stats claim songs.
_INFORMATIONAL = frozenset({"tabs", "eras", "songs", "versions", "pct_era_zero_song"})


def compare(now: dict[str, Any], base: dict[str, Any]) -> int:
    """Print a before/after table. Returns the number of regressions."""
    regressions = 0
    print(f"{'metric':40s} {'baseline':>12s} {'now':>12s} {'delta':>12s}")
    print("-" * 80)
    for key in now:
        if key not in base:
            continue
        a, b = base[key], now[key]
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        delta = round(b - a, 2)
        if key in _INFORMATIONAL:
            worse = False
        elif key.startswith("defect_") or key in _LOWER_IS_BETTER:
            worse = delta > 0
        else:
            worse = delta < 0
        flag = "  REGRESSION" if worse and delta else ""
        if worse and delta:
            regressions += 1
        if delta or flag:
            print(f"{key:40s} {a:>12} {b:>12} {delta:>+12}{flag}")
    print("-" * 80)
    print(f"{regressions} regression(s)")
    return regressions


def report(t: Totals) -> None:
    m = to_metrics(t)
    print(f"corpus: {t.tabs} tabs parsed, {t.tabs_failed} failed")
    print(f"  eras={t.eras} songs={t.songs} versions={t.versions} rows={t.rows}")
    print()
    print("coverage:")
    for k in ("pct_era_art", "pct_era_zero_song", "pct_rows_skipped"):
        print(f"  {k:34s} {m[k]:7.2f}%")
    print()
    print("defects:")
    for k, v in m.items():
        if k.startswith("defect_"):
            print(f"  {k:34s} {v:7d}")
    print()
    print("field coverage:")
    for f in VERSION_FIELDS:
        print(f"  {f:22s} {t.field_hits[f]:8d}  {m[f'pct_field_{f}']:6.2f}%")
    if t.unmatched_stat_labels:
        print()
        print("unrecognised era-stat labels (top 25):")
        for k, v in t.unmatched_stat_labels.most_common(25):
            print(f"  {v:6d}  {k}")
    if t.dropped_columns:
        print()
        print("unmapped columns — alias gaps (top 25):")
        for k, v in t.dropped_columns.most_common(25):
            print(f"  {v:6d}  {k}")
    if t.duplicate_columns:
        print()
        print("duplicate columns — a claimed field's second column (top 15):")
        for k, v in t.duplicate_columns.most_common(15):
            print(f"  {v:6d}  {k}")
    if t.art_hosts:
        print()
        print("art hosts:", dict(t.art_hosts.most_common(8)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=".cache", help="directory of captured *.html")
    ap.add_argument("--limit", type=int, default=0, help="max tabs (0 = all)")
    ap.add_argument("--min-size", type=int, default=20_000)
    ap.add_argument("--max-size", type=int, default=4_000_000)
    ap.add_argument("--out", help="write metrics JSON here")
    ap.add_argument(
        "--detail",
        help="write per-workbook JSON keyed by tab URL here. "
             "Aggregates hide which tracker moved; diffing two detail files "
             "shows whether a ratio shifted because trackers got worse or "
             "because more eras were discovered.",
    )
    ap.add_argument("--baseline", help="compare against this metrics JSON")
    ap.add_argument("--report", action="store_true", help="print the full report")
    ap.add_argument(
        "--all-tabs", action="store_true",
        help="sweep every cached tab instead of one main tab per workbook "
             "(debugging; ratios are not comparable to the default mode)",
    )
    args = ap.parse_args()

    logging.disable(logging.CRITICAL)  # the parser logs unmatched rows per tab

    if not os.path.isdir(args.corpus):
        print(f"corpus not found: {args.corpus}", file=sys.stderr)
        return 2

    t = collect(
        args.corpus, args.limit, args.min_size, args.max_size,
        per_sheet=not args.all_tabs,
    )
    metrics = to_metrics(t)

    if args.report or not (args.out or args.baseline):
        report(t)
    if args.detail:
        with open(args.detail, "w") as fh:
            json.dump(t.detail, fh, indent=2, sort_keys=True)
        print(f"wrote {args.detail}")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(metrics, fh, indent=2, sort_keys=True)
        print(f"wrote {args.out}")
    if args.baseline:
        with open(args.baseline) as fh:
            base = json.load(fh)
        return 1 if compare(metrics, base) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
