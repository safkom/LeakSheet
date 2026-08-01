#!/usr/bin/env python3
"""ArtistGrid format-difference sweep — the "50+ trackers, each different" analysis.

Fetches the live ArtistGrid registry (successor to the dead TrackerHub master
sheet; the older artists.ndjson file is deprecated too), then for every
up-to-date tracker:

  1. GETs the base /htmlview page and classifies every discovered tab name
     against the fetcher's keyword sets (main/art/content kinds) — unrecognized
     tab names are the tab-vocabulary gap evidence.
  2. Runs the real ``async_fetch_and_parse`` end-to-end and harvests:
     - parse-health verdict (tests/_health.live_violations)
     - parse signals: rows/skips/fuzzy/dropped_columns/unmatched samples
     - census distributions (quality/availability/type/badges/link hosts,
       streamable share via the real resolve_stream_url)
     - DATE-FORMAT histogram for file_date/leak_date — classified against the
       four formats the iOS client can parse (everything else degrades to
       year-only or zero on the client)

Artifacts: tests/results/sweep-<date>/<slug>.json per tracker plus
_aggregate.json (cross-tracker gap lists). tests/results/ is gitignored.

Usage:
    python3 scripts/tools/trackerhub_sweep.py [--limit N] [--only substr]
            [--concurrency 5] [--include-stale]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from src.config import ARTISTGRID_URL
from src.parser import parse_artistgrid_csv
from src.fetcher import (
    FetchError,
    USER_AGENT,
    _clean_tab_name,
    _discover_named_tabs,
    _get_art_tab_gid,
    _get_content_tabs,
    _get_unreleased_tab_gid,
    _normalize_url,
    async_fetch_and_parse,
)
from tests._health import live_violations
from tests.tools.census import census_artist, _slugify

OUT_DIR = ROOT / "tests" / "results" / f"sweep-{time.strftime('%Y%m%d')}"

# ---------------------------------------------------------------------------
# Date-format classification — mirrors what the iOS client can actually parse
# (ArtistViewModel tries MM/dd/yyyy, yyyy-MM-dd, MMMM yyyy, then a bare
# 4-digit-year regex; anything else sorts as year-only or zero).
# ---------------------------------------------------------------------------
_MONTHS_FULL = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_MONTHS_ABBR = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
_DATE_CLASSES: list[tuple[str, re.Pattern, str]] = [
    ("MM/dd/yyyy",     re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "ios-full"),
    ("yyyy-MM-dd",     re.compile(r"^\d{4}-\d{2}-\d{2}$"), "ios-full"),
    ("MMMM yyyy",      re.compile(rf"^(?:{_MONTHS_FULL}) \d{{4}}$"), "ios-full"),
    ("yyyy",           re.compile(r"^\d{4}$"), "ios-full"),
    ("MMM d, yyyy",    re.compile(rf"^(?:{_MONTHS_ABBR})\.? \d{{1,2}},? \d{{4}}$"), "ios-year-only"),
    ("MMMM d, yyyy",   re.compile(rf"^(?:{_MONTHS_FULL}) \d{{1,2}},? \d{{4}}$"), "ios-year-only"),
    ("MMM yyyy",       re.compile(rf"^(?:{_MONTHS_ABBR})\.? \d{{4}}$"), "ios-year-only"),
    ("dd/MM_or_MM/dd (2-digit yr)", re.compile(r"^\d{1,2}/\d{1,2}/\d{2}$"), "ios-zero"),
    ("d Month yyyy",   re.compile(rf"^\d{{1,2}} (?:{_MONTHS_FULL}|{_MONTHS_ABBR})\.? \d{{4}}$"), "ios-year-only"),
    ("n/a-ish",        re.compile(r"^(n/?a|none|unknown|\?+|tbd|-+)$", re.IGNORECASE), "absent"),
]


def classify_date(value: str) -> tuple[str, str]:
    v = value.strip()
    if not v:
        return ("empty", "absent")
    for name, pat, ios in _DATE_CLASSES:
        if pat.match(v):
            return (name, ios)
    # contains a 4-digit year somewhere → iOS's bare-year regex still catches it
    if re.search(r"(?:19|20)\d{2}", v):
        return ("other-with-year", "ios-year-only")
    return ("other-no-year", "ios-zero")


def harvest_dates(artist) -> dict:
    fmt_hist: Counter[str] = Counter()
    ios_hist: Counter[str] = Counter()
    samples: dict[str, str] = {}
    for era in artist.eras:
        for song in era.songs:
            for v in song.versions:
                for value in (v.file_date, v.leak_date):
                    if value is None:
                        continue
                    fmt, ios = classify_date(value)
                    fmt_hist[fmt] += 1
                    ios_hist[ios] += 1
                    samples.setdefault(fmt, value.strip()[:40])
    return {
        "formats": dict(fmt_hist.most_common()),
        "ios_parseability": dict(ios_hist.most_common()),
        "samples": samples,
    }


def classify_tabs(named_tabs: dict[str, str]) -> dict:
    """Bucket every discovered tab into recognized kinds / unrecognized names."""
    content = {gid: kind for gid, kind, _name in _get_content_tabs(named_tabs)}
    art_gid = _get_art_tab_gid(named_tabs)
    unreleased_gid = _get_unreleased_tab_gid(named_tabs)
    recognized: dict[str, str] = {}
    unrecognized: list[str] = []
    for gid, name in named_tabs.items():
        if gid == unreleased_gid:
            recognized[name] = "main"
        elif gid == art_gid:
            recognized[name] = "art"
        elif gid in content:
            recognized[name] = content[gid]
        else:
            unrecognized.append(name)
    return {"recognized": recognized, "unrecognized": unrecognized}


async def sweep_one(entry, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> dict:
    slug = _slugify(entry.name)
    result: dict = {"name": entry.name, "url": entry.url, "slug": slug, "best": entry.best}
    async with sem:
        t0 = time.monotonic()
        # 1. Base page → tab inventory (independent of the parse pipeline).
        try:
            base = await client.get(_normalize_url(entry.url), timeout=30)
            base.raise_for_status()
            named_tabs = _discover_named_tabs(base.text)
            result["tabs"] = classify_tabs(named_tabs)
            result["tab_count"] = len(named_tabs)
        except Exception as e:  # noqa: BLE001 — inventory is best-effort
            result["tabs_error"] = f"{type(e).__name__}: {str(e)[:120]}"

        # 2. Full pipeline parse.
        try:
            artist = await async_fetch_and_parse(
                entry.url, artist_name=entry.name, use_cache=True, cache_ttl=6 * 3600
            )
        except FetchError as e:
            result["status"] = "fetch_error"
            result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            return result
        except Exception as e:  # noqa: BLE001 — a crash on one tracker is a finding
            result["status"] = "crash"
            result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            return result
        result["fetch_s"] = round(time.monotonic() - t0, 1)

    violations = live_violations(artist)
    result["status"] = "violations" if violations else "ok"
    result["violations"] = violations
    result["census"] = census_artist(artist, source=entry.url, origin="sweep")
    result["dates"] = harvest_dates(artist)
    result["api_tabs"] = [
        {"kind": t.kind, "name": t.name, "entries": len(t.entries)}
        for t in (artist.tabs or [])
    ]
    return result


def aggregate(results: list[dict]) -> dict:
    """Cross-tracker gap lists — the evidence base for B3 fixes."""
    agg: dict = {"trackers": len(results)}
    agg["status_counts"] = dict(Counter(r.get("status", "?") for r in results))
    agg["errors"] = {
        r["name"]: r["error"] for r in results if r.get("status") in ("fetch_error", "crash")
    }
    agg["violating"] = {
        r["name"]: r["violations"] for r in results if r.get("status") == "violations"
    }
    dropped: Counter[str] = Counter()
    unmatched_examples: dict[str, list[str]] = {}
    skip_rates: dict[str, float] = {}
    for r in results:
        c = r.get("census")
        if not c:
            continue
        ps = c["parse_signals"]
        for col in ps.get("dropped_columns", []):
            dropped[col.lower()] += 1
        if ps.get("unmatched_rows"):
            unmatched_examples[r["name"]] = ps["unmatched_rows"][:3]
        if ps.get("skipped_ratio_pct"):
            skip_rates[r["name"]] = ps["skipped_ratio_pct"]
    agg["dropped_columns"] = dict(dropped.most_common())
    agg["skip_rates_pct"] = dict(sorted(skip_rates.items(), key=lambda kv: -kv[1]))
    agg["unmatched_examples"] = unmatched_examples
    unrec: Counter[str] = Counter()
    for r in results:
        for name in (r.get("tabs") or {}).get("unrecognized", []):
            unrec[_clean_tab_name(name)] += 1
    agg["unrecognized_tabs"] = dict(unrec.most_common())
    date_fmt: Counter[str] = Counter()
    ios_parse: Counter[str] = Counter()
    for r in results:
        for fmt, n in (r.get("dates") or {}).get("formats", {}).items():
            date_fmt[fmt] += n
        for k, n in (r.get("dates") or {}).get("ios_parseability", {}).items():
            ios_parse[k] += n
    agg["date_formats"] = dict(date_fmt.most_common())
    agg["date_ios_parseability"] = dict(ios_parse.most_common())
    quality: Counter[str] = Counter()
    avail: Counter[str] = Counter()
    hosts: Counter[str] = Counter()
    streamable_links = total_links = 0
    for r in results:
        c = r.get("census")
        if not c:
            continue
        for k, n in c["distributions"]["quality"].items():
            quality[k] += n
        for k, n in c["distributions"]["availability"].items():
            avail[k] += n
        for k, n in c["distributions"]["link_hosts"].items():
            hosts[k] += n
        streamable_links += c["totals"]["streamable_links"]
        total_links += c["totals"]["links"]
    agg["quality_vocab"] = dict(quality.most_common(40))
    agg["availability_vocab"] = dict(avail.most_common(40))
    agg["link_hosts"] = dict(hosts.most_common(40))
    agg["streamable_pct_overall"] = round(100 * streamable_links / total_links, 1) if total_links else 0.0
    return agg


async def main_async(args) -> int:
    async with httpx.AsyncClient(
        follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = await client.get(ARTISTGRID_URL, headers={"Accept": "text/csv"}, timeout=30)
        resp.raise_for_status()
        entries = parse_artistgrid_csv(resp.text)
        targets = entries if args.include_stale else [e for e in entries if e.up_to_date]
        if args.only:
            targets = [e for e in targets if args.only.lower() in e.name.lower()]
        if args.limit:
            targets = targets[: args.limit]
        print(f"ArtistGrid: {len(entries)} entries, sweeping {len(targets)} "
              f"({'all' if args.include_stale else 'up-to-date only'})")

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        sem = asyncio.Semaphore(args.concurrency)
        results: list[dict] = []
        done = 0

        async def run(entry):
            nonlocal done
            r = await sweep_one(entry, client, sem)
            results.append(r)
            done += 1
            (OUT_DIR / f"{r['slug']}.json").write_text(
                json.dumps(r, indent=2, ensure_ascii=False)
            )
            c = r.get("census", {}).get("totals", {})
            mark = {"ok": "+", "violations": "!", "fetch_error": "-", "crash": "X"}.get(r["status"], "?")
            print(f"[{mark}] {done:3d}/{len(targets)} {r['name'][:34]:<35} "
                  f"{c.get('eras', 0):3d}E {c.get('songs', 0):5d}S  {r.get('status')}")

        await asyncio.gather(*[run(e) for e in targets])

    agg = aggregate(results)
    (OUT_DIR / "_aggregate.json").write_text(json.dumps(agg, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(results)} tracker artifacts + _aggregate.json to {OUT_DIR.relative_to(ROOT)}/")
    print(f"Status: {agg['status_counts']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="TrackerHub format-difference sweep")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", type=str, default=None)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--include-stale", action="store_true",
                    help="also sweep trackers TrackerHub marks as not up-to-date")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
