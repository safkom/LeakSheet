#!/usr/bin/env python3
"""Tracker census — condensed, tagged content report per tracker.

Parses the locked set of live trackers and/or the local fixtures and emits,
per tracker, a markdown report + machine-readable JSON covering:

  * era table (sections, song/version counts, art, description)
  * distributions: badges, version tags, quality, availability, type,
    link hosts (split into app-streamable vs not)
  * metadata coverage: notes, samples, OG filenames, credits, dates
  * parse-error signals: unmatched rows, dropped columns, fuzzy matches,
    skipped ratio
  * suspicion heuristics: 0-song eras, single-song eras, >=10-version songs,
    duplicate titles across eras, placeholder (???) clusters, era-looking
    song names, over-long names

Live-tracker HTML (the winning tab actually parsed) is snapshotted gzipped
under tests/fixtures/snapshots/ so accuracy baselines can be pinned on the
exact bytes this census saw.

Usage:
    python3 -m tests.tools.census --fixtures            # offline, 4 fixtures
    python3 -m tests.tools.census --live --fresh        # 7 locked live URLs
    python3 -m tests.tools.census --all
    python3 -m tests.tools.census --live --only yetracker
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.config import discover_trackers
from src.fetcher import (
    FetchError,
    _get_cached,
    _normalize_url,
    fetch_and_parse,
)
from src.models import Artist
from src.parser import _PLACEHOLDER_BASE_NAMES, parse_file

# The locked live set for the 2026-07-06 deep review (user-verified fresh).
LIVE_TRACKERS: list[tuple[str, str]] = [
    ("yetracker", "https://yetracker.net/"),
    ("tracker-1gJq", "https://docs.google.com/spreadsheets/d/1gJqbQrb3dIWF-PLMsKkNUrftpQb8zxsZFDAIpSvT5Fo/htmlview#gid=1807066929"),
    ("tracker-1i4O", "https://docs.google.com/spreadsheets/d/1i4OQglDHiiqMDthqfUFPutGmpZzK7n63LaoWApqhQXI/htmlview"),
    ("tracker-1v55", "https://docs.google.com/spreadsheets/d/1v55XAPLzw1iuWxH1OQKajCIYPhW2BXcLoV4mXDZ55DI/htmlview"),
    ("tracker-1_SN", "https://docs.google.com/spreadsheets/d/1_SNZQS-AAXVleukgKlraegaozkLOu8WMHbUwmPm61hc/htmlview"),
    ("tracker-1zqq", "https://docs.google.com/spreadsheets/d/1zqqdIds1iwnx4lh29iF1IlraeuqfGhxH9qLNlWOnryo/htmlview"),
    ("tracker-1Irt", "https://docs.google.com/spreadsheets/d/1Irtfvymu26CShYowLMMfD-rM0o9CJqE6-BBSlYsAaF4/htmlview"),
]

# Hosts the backend /stream proxy can serve (mirror of api.py allowlist —
# test tool only, kept in sync manually).
STREAMABLE_HOSTS = {
    "pillows.su", "pillowcase.su", "api.pillows.su",
    "imgur.gg", "temp.imgur.gg",
    "music.froste.lol", "froste.lol",
    "krakenfiles.com", "cdn.krakenfiles.com",
}

SNAPSHOT_DIR_DEFAULT = ROOT / "tests" / "fixtures" / "snapshots"
OUT_DIR_DEFAULT = ROOT / "tests" / "results" / "census"

# Song names that smell like mis-classified era/stat rows.
_STATS_LIKE = re.compile(r"\b\d+\s+(?:OG\s*File|Track|Song|Snippet|Leak)", re.IGNORECASE)
_YEAR_RANGE = re.compile(r"\(\s*(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)?\d{2})?\s*\)")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unnamed"


def _host(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc.removeprefix("www.")


def census_artist(artist: Artist, source: str, origin: str) -> dict:
    """Reduce a parsed Artist to the census dict."""
    eras = []
    badge_hist: Counter[str] = Counter()
    tag_hist: Counter[str] = Counter()
    quality_hist: Counter[str] = Counter()
    avail_hist: Counter[str] = Counter()
    type_hist: Counter[str] = Counter()
    host_hist: Counter[str] = Counter()

    n_versions = 0
    n_songs = 0
    cov = Counter()  # metadata coverage counts over versions

    zero_song_eras: list[dict] = []
    single_song_eras: list[str] = []
    big_songs: list[dict] = []
    placeholder_groups: list[dict] = []
    era_like_names: list[dict] = []
    long_names: list[dict] = []
    song_era_index: dict[str, set[str]] = {}

    for era in artist.eras:
        eras.append({
            "name": era.name,
            "alt_names": era.alt_names,
            "sections": [sec.name for sec in era.sections],
            "songs": era.song_count,
            "versions": era.version_count,
            "has_art": bool(era.art_url),
            "has_description": bool(era.description),
            "has_stats": bool(era.stats or era.stats_raw),
            "timeline_events": len(era.timeline or []),
        })
        if era.song_count == 0:
            zero_song_eras.append({
                "era": era.name,
                "has_description": bool(era.description),
                "has_timeline": bool(era.timeline),
            })
        elif era.song_count == 1:
            single_song_eras.append(era.name)

        for song in era.songs:
            n_songs += 1
            key = song.base_name.strip().lower()
            if key not in _PLACEHOLDER_BASE_NAMES:
                song_era_index.setdefault(key, set()).add(era.name)
            if song.badge:
                badge_hist[song.badge.value] += 1
            if len(song.versions) >= 10:
                big_songs.append({
                    "song": song.base_name, "versions": len(song.versions), "era": era.name,
                })
            if key in _PLACEHOLDER_BASE_NAMES and len(song.versions) > 1:
                placeholder_groups.append({
                    "era": era.name,
                    "base": song.base_name,
                    "versions": len(song.versions),
                    "alt_title_clusters": sorted({
                        t for v in song.versions for t in (v.alt_titles or [])
                    }),
                })
            if _STATS_LIKE.search(song.base_name) or _YEAR_RANGE.search(song.base_name):
                era_like_names.append({"era": era.name, "song": song.base_name})
            if len(song.base_name) > 80:
                long_names.append({"era": era.name, "song": song.base_name[:120]})

            for v in song.versions:
                n_versions += 1
                if v.version_tag:
                    tag_hist[v.version_tag] += 1
                if v.quality:
                    quality_hist[v.quality.strip()] += 1
                if v.available_length:
                    avail_hist[v.available_length.strip()] += 1
                if v.type:
                    type_hist[v.type.strip()] += 1
                for link in v.links:
                    host_hist[_host(link)] += 1
                for field in ("notes", "samples", "og_filenames", "featuring",
                              "producers", "track_length", "file_date",
                              "leak_date", "quality", "available_length"):
                    if getattr(v, field):
                        cov[field] += 1

    dup_songs = [
        {"song": key, "eras": sorted(eras_)}
        for key, eras_ in sorted(song_era_index.items())
        if len(eras_) > 1
    ]

    md = artist.parse_metadata
    coverage = {
        field: {"count": cov[field], "pct": round(100 * cov[field] / n_versions, 1) if n_versions else 0.0}
        for field in ("notes", "samples", "og_filenames", "featuring", "producers",
                      "track_length", "file_date", "leak_date", "quality", "available_length")
    }
    streamable = sum(c for h, c in host_hist.items() if h in STREAMABLE_HOSTS)
    total_links = sum(host_hist.values())

    return {
        "artist": artist.name,
        "slug": artist.slug,
        "source": source,
        "origin": origin,
        "totals": {
            "eras": len(artist.eras),
            "songs": n_songs,
            "versions": n_versions,
            "misc_entries": len(artist.misc_entries),
            "notices": len(artist.notices),
            "links": total_links,
            "streamable_links": streamable,
            "streamable_pct": round(100 * streamable / total_links, 1) if total_links else 0.0,
        },
        "eras": eras,
        "distributions": {
            "badges": dict(badge_hist.most_common()),
            "version_tags": dict(tag_hist.most_common(25)),
            "quality": dict(quality_hist.most_common(20)),
            "availability": dict(avail_hist.most_common(20)),
            "type": dict(type_hist.most_common(20)),
            "link_hosts": dict(host_hist.most_common(25)),
        },
        "misc_entry_types": dict(Counter(
            (e.entry_type or "(none)").strip() for e in artist.misc_entries
        ).most_common()),
        "coverage": coverage,
        "parse_signals": {
            "total_rows": md.total_rows if md else None,
            "song_rows": md.song_rows if md else None,
            "skipped_rows": md.skipped_rows if md else None,
            "skipped_ratio_pct": round(100 * md.skipped_rows / md.total_rows, 2) if md and md.total_rows else None,
            "footer_rows": md.footer_rows if md else None,
            "fuzzy_matched_rows": md.fuzzy_matched_rows if md else None,
            "dropped_columns": md.dropped_columns if md else [],
            "unmatched_rows": md.unmatched_rows if md else [],
            "unmatched_rows_total": md.unmatched_rows_total if md else None,
        },
        "suspicions": {
            "zero_song_eras": zero_song_eras,
            "single_song_eras": single_song_eras,
            "songs_10plus_versions": sorted(big_songs, key=lambda d: -d["versions"]),
            "duplicate_songs_across_eras": dup_songs,
            "placeholder_groups": placeholder_groups,
            "era_like_song_names": era_like_names,
            "over_long_names": long_names,
        },
    }


def _hist_lines(hist: dict[str, int], limit: int = 15) -> list[str]:
    return [f"| {k or '(empty)'} | {v} |" for k, v in list(hist.items())[:limit]]


def render_markdown(c: dict) -> str:
    t = c["totals"]
    s = c["parse_signals"]
    sus = c["suspicions"]
    lines = [
        f"# Census — {c['artist']}",
        "",
        f"- Source: `{c['source']}` ({c['origin']})",
        f"- Eras **{t['eras']}** · Songs **{t['songs']}** · Versions **{t['versions']}**"
        f" · Misc entries **{t['misc_entries']}** · Notices **{t['notices']}**",
        f"- Links **{t['links']}**, app-streamable **{t['streamable_links']}** ({t['streamable_pct']}%)",
        "",
        "## Eras",
        "",
        "| Era | Sections | Songs | Versions | Art | Desc | Stats |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in c["eras"]:
        secs = ", ".join(n or "(default)" for n in e["sections"]) or "—"
        lines.append(
            f"| {e['name']} | {secs} | {e['songs']} | {e['versions']} | "
            f"{'✓' if e['has_art'] else '·'} | {'✓' if e['has_description'] else '·'} | "
            f"{'✓' if e['has_stats'] else '·'} |"
        )

    for title, key in (("Badges", "badges"), ("Version tags", "version_tags"),
                       ("Quality", "quality"), ("Availability", "availability"),
                       ("Type", "type"), ("Link hosts", "link_hosts")):
        hist = c["distributions"][key]
        if not hist:
            continue
        lines += ["", f"## {title}", "", "| Value | Count |", "|---|---|", *_hist_lines(hist)]

    if c["misc_entry_types"]:
        lines += ["", "## Misc entry types", "", "| Type | Count |", "|---|---|",
                  *_hist_lines(c["misc_entry_types"])]

    lines += ["", "## Metadata coverage (of versions)", "", "| Field | Count | % |", "|---|---|---|"]
    for field, d in c["coverage"].items():
        lines.append(f"| {field} | {d['count']} | {d['pct']}% |")

    lines += [
        "", "## Parse signals", "",
        f"- Rows: total **{s['total_rows']}**, song **{s['song_rows']}**, "
        f"footer **{s['footer_rows']}**, skipped **{s['skipped_rows']}** ({s['skipped_ratio_pct']}%)",
        f"- Fuzzy era matches: **{s['fuzzy_matched_rows']}**",
        f"- Dropped columns: {', '.join(s['dropped_columns']) or 'none'}",
    ]
    if s["unmatched_rows"]:
        lines += ["", "### Unmatched rows", ""]
        lines += [f"- `{row[:160]}`" for row in s["unmatched_rows"]]

    lines += ["", "## Suspicions", ""]
    def block(title: str, items: list, fmt) -> None:
        lines.append(f"### {title} ({len(items)})")
        lines.append("")
        for it in items[:30]:
            lines.append(f"- {fmt(it)}")
        if len(items) > 30:
            lines.append(f"- … {len(items) - 30} more")
        lines.append("")

    block("Zero-song eras", sus["zero_song_eras"],
          lambda d: f"**{d['era']}** (desc={d['has_description']}, timeline={d['has_timeline']})")
    block("Single-song eras", sus["single_song_eras"], lambda name: name)
    block("Songs with ≥10 versions", sus["songs_10plus_versions"],
          lambda d: f"{d['versions']}× **{d['song']}** ({d['era']})")
    block("Duplicate song titles across eras", sus["duplicate_songs_across_eras"],
          lambda d: f"**{d['song']}** in: {'; '.join(d['eras'])}")
    block("Placeholder groups", sus["placeholder_groups"],
          lambda d: f"{d['versions']}× **{d['base']}** ({d['era']}) alt-titles: {', '.join(d['alt_title_clusters']) or '(none)'}")
    block("Era-like song names", sus["era_like_song_names"],
          lambda d: f"**{d['song']}** ({d['era']})")
    block("Over-long names (>80 chars)", sus["over_long_names"],
          lambda d: f"{d['song']} ({d['era']})")

    return "\n".join(lines) + "\n"


def _write_outputs(c: dict, slug: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{slug}.json").write_text(json.dumps(c, indent=2, ensure_ascii=False))
    (out_dir / f"{slug}.md").write_text(render_markdown(c))


def _snapshot_live_html(
    url: str, slug: str, snapshot_dir: Path, not_before: float
) -> str | None:
    """Persist the winning-tab HTML fetch_and_parse cached for this URL.

    Only snapshots cache entries written after ``not_before`` (the census run
    start) — a stale entry must never be pinned as a fresh fixture.
    """
    from src.fetcher import CACHE_DIR, _cache_key  # local import: private helpers

    url_norm = _normalize_url(url)
    cached = _get_cached(url_norm, cache_ttl=10**9)
    if not cached:
        return None
    meta_path = CACHE_DIR / f"{_cache_key(url_norm)}.meta.json"
    try:
        written_at = json.loads(meta_path.read_text()).get("timestamp", 0)
    except (OSError, ValueError):
        written_at = 0
    if written_at < not_before:
        return None  # stale — refuse to snapshot
    html, _title = cached
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{slug}.html.gz"
    path.write_bytes(gzip.compress(html.encode("utf-8")))
    return str(path.relative_to(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="Tracker census generator")
    ap.add_argument("--live", action="store_true", help="census the locked live tracker URLs")
    ap.add_argument("--fixtures", action="store_true", help="census the local Trackers/ fixtures")
    ap.add_argument("--all", action="store_true", help="both --live and --fixtures")
    ap.add_argument("--fresh", action="store_true",
                    help="clear .cache/ before live fetches (fetch fresh but keep "
                         "caching on so the winning HTML can be snapshotted)")
    ap.add_argument("--no-snapshot", action="store_true", help="skip writing HTML snapshots")
    ap.add_argument("--only", type=str, help="substring filter on slug/artist name")
    ap.add_argument("--out", type=Path, default=OUT_DIR_DEFAULT)
    ap.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR_DEFAULT)
    args = ap.parse_args()

    do_live = args.live or args.all
    do_fixtures = args.fixtures or args.all
    if not (do_live or do_fixtures):
        ap.error("pick --live, --fixtures, or --all")

    summary: list[dict] = []

    if do_fixtures:
        for artist_name, sheet_path in discover_trackers():
            slug = f"fixture-{_slugify(artist_name)}"
            if args.only and args.only.lower() not in slug and args.only.lower() not in artist_name.lower():
                continue
            t0 = time.time()
            print(f"[fixture] {artist_name:<30} ", end="", flush=True)
            try:
                artist = parse_file(sheet_path, artist_name)
            except Exception as exc:  # census must survive any single failure
                print(f"💥 {type(exc).__name__}: {exc}")
                summary.append({"slug": slug, "status": f"ERROR: {type(exc).__name__}", "url": str(sheet_path)})
                continue
            c = census_artist(artist, source=str(sheet_path.relative_to(ROOT)), origin="fixture")
            _write_outputs(c, slug, args.out)
            dt = time.time() - t0
            print(f"eras={c['totals']['eras']} songs={c['totals']['songs']} "
                  f"versions={c['totals']['versions']} skipped={c['parse_signals']['skipped_rows']} "
                  f"({dt:.1f}s)")
            summary.append({"slug": slug, "status": "OK", **c["totals"],
                            "skipped": c["parse_signals"]["skipped_rows"],
                            "fuzzy": c["parse_signals"]["fuzzy_matched_rows"],
                            "dropped_columns": c["parse_signals"]["dropped_columns"]})

    if do_live:
        run_started = time.time()
        if args.fresh:
            from src.fetcher import CACHE_DIR
            removed = 0
            if CACHE_DIR.exists():
                for f in CACHE_DIR.iterdir():
                    if f.suffix in (".html", ".json"):
                        f.unlink()
                        removed += 1
            print(f"[fresh]   cleared {removed} cache files from {CACHE_DIR.name}/")
        for slug, url in LIVE_TRACKERS:
            if args.only and args.only.lower() not in slug.lower() and args.only.lower() not in url.lower():
                continue
            t0 = time.time()
            print(f"[live]    {slug:<30} ", end="", flush=True)
            try:
                artist = fetch_and_parse(url, use_cache=True)
            except FetchError as exc:
                print(f"🚫 {type(exc).__name__}: {str(exc)[:140]}")
                summary.append({"slug": slug, "status": f"FETCH_ERR: {type(exc).__name__}", "url": url})
                continue
            except Exception as exc:
                print(f"💥 {type(exc).__name__}: {str(exc)[:140]}")
                summary.append({"slug": slug, "status": f"ERROR: {type(exc).__name__}", "url": url})
                continue
            c = census_artist(artist, source=url, origin="live")
            snap = None if args.no_snapshot else _snapshot_live_html(
                url, slug, args.snapshot_dir, not_before=run_started
            )
            c["snapshot"] = snap
            _write_outputs(c, slug, args.out)
            dt = time.time() - t0
            print(f"eras={c['totals']['eras']} songs={c['totals']['songs']} "
                  f"versions={c['totals']['versions']} skipped={c['parse_signals']['skipped_rows']} "
                  f"snap={'✓' if snap else '✗'} ({dt:.1f}s)")
            summary.append({"slug": slug, "status": "OK", "artist": c["artist"], **c["totals"],
                            "skipped": c["parse_signals"]["skipped_rows"],
                            "fuzzy": c["parse_signals"]["fuzzy_matched_rows"],
                            "dropped_columns": c["parse_signals"]["dropped_columns"],
                            "snapshot": snap})

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(summary)} census entries to {args.out.relative_to(ROOT)}/")
    failures = [s for s in summary if s["status"] != "OK"]
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  {f['slug']}: {f['status']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
