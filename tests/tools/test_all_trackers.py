#!/usr/bin/env python3
"""Mass-test all trackers from the artistgrid NDJSON feed.

Fetches each spreadsheet, parses it, and reports era/song counts.
Flags trackers where parsing produces 0 eras or suspiciously few songs.

Usage:
    python3 -m tests.tools.test_all_trackers [--limit N] [--no-cache] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.fetcher import fetch_and_parse, FetchError, AccessDeniedError

NDJSON_PATH = Path(__file__).resolve().parent.parent.parent / "Trackers" / "artists.ndjson"
NDJSON_URL_FALLBACK = Path.home() / "Downloads" / "artists.ndjson"

SHEET_ID_RE = re.compile(r"/d/([A-Za-z0-9_-]+)")


def load_artists(path: Path) -> list[dict]:
    """Load artist entries from NDJSON file."""
    artists = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            artists.append(json.loads(line))
    return artists


def build_url(entry: dict) -> str | None:
    """Build htmlview URL from the entry's url field."""
    url = entry.get("url", "")
    if not url:
        return None
    m = SHEET_ID_RE.search(url)
    if not m:
        return None
    sheet_id = m.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview"


def test_tracker(name: str, url: str, use_cache: bool = True, verbose: bool = False) -> dict:
    """Fetch and parse a single tracker, returning results dict."""
    result = {
        "name": name,
        "url": url,
        "status": "unknown",
        "eras": 0,
        "songs": 0,
        "versions": 0,
        "song_rows": 0,
        "skipped_rows": 0,
        "unmatched_rows": 0,
        "fuzzy_matched": 0,
        "error": None,
        "time_s": 0.0,
    }

    t0 = time.time()
    try:
        artist = fetch_and_parse(url, artist_name=name, use_cache=use_cache)
        elapsed = time.time() - t0
        result["time_s"] = round(elapsed, 1)

        n_eras = len(artist.eras)
        n_songs = sum(
            len(song.versions)
            for era in artist.eras
            for section in era.sections
            for song in section.songs
        )
        n_unique_songs = sum(
            len(section.songs)
            for era in artist.eras
            for section in era.sections
        )

        result["eras"] = n_eras
        result["songs"] = n_unique_songs
        result["versions"] = n_songs

        if artist.parse_metadata:
            result["song_rows"] = artist.parse_metadata.song_rows
            result["skipped_rows"] = artist.parse_metadata.skipped_rows
            result["unmatched_rows"] = len(artist.parse_metadata.unmatched_rows)
            result["fuzzy_matched"] = artist.parse_metadata.fuzzy_matched_rows

        if n_eras == 0:
            result["status"] = "FAIL_NO_ERAS"
        elif n_songs == 0:
            result["status"] = "FAIL_NO_SONGS"
        elif result["unmatched_rows"] > result["song_rows"] * 0.3:
            result["status"] = "WARN_MANY_UNMATCHED"
        else:
            result["status"] = "OK"

        if verbose and artist.parse_metadata and artist.parse_metadata.unmatched_rows:
            result["unmatched_samples"] = artist.parse_metadata.unmatched_rows[:10]

        if verbose:
            era_details = []
            for era in artist.eras:
                era_songs = sum(len(s.songs) for s in era.sections)
                era_details.append(f"  {era.name or '(unnamed)'}: {era_songs} songs")
            result["era_details"] = era_details

    except AccessDeniedError as e:
        elapsed = time.time() - t0
        result["time_s"] = round(elapsed, 1)
        result["status"] = "BANNED"
        result["error"] = str(e)[:200]
    except FetchError as e:
        elapsed = time.time() - t0
        result["time_s"] = round(elapsed, 1)
        result["status"] = f"FETCH_ERR"
        result["error"] = str(e)[:200]
    except Exception as e:
        elapsed = time.time() - t0
        result["time_s"] = round(elapsed, 1)
        result["status"] = "PARSE_ERR"
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"

    return result


def main():
    parser = argparse.ArgumentParser(description="Mass-test all trackers")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of trackers to test")
    parser.add_argument("--no-cache", action="store_true", help="Disable caching")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-era details")
    parser.add_argument("--ndjson", type=str, help="Path to artists.ndjson")
    parser.add_argument("--only", type=str, help="Test only this artist (substring match)")
    args = parser.parse_args()

    # Find NDJSON file
    ndjson_path = Path(args.ndjson) if args.ndjson else None
    if not ndjson_path:
        if NDJSON_PATH.exists():
            ndjson_path = NDJSON_PATH
        elif NDJSON_URL_FALLBACK.exists():
            ndjson_path = NDJSON_URL_FALLBACK
        else:
            print(f"ERROR: Cannot find artists.ndjson at {NDJSON_PATH} or {NDJSON_URL_FALLBACK}")
            sys.exit(1)

    artists = load_artists(ndjson_path)
    print(f"Loaded {len(artists)} artists from {ndjson_path}\n")

    if args.only:
        artists = [a for a in artists if args.only.lower() in a["name"].lower()]
        print(f"Filtered to {len(artists)} matching '{args.only}'\n")

    if args.limit:
        artists = artists[:args.limit]

    results = []
    ok = fail = warn = err = banned = 0

    for i, entry in enumerate(artists):
        name = entry["name"]
        url = build_url(entry)
        if not url:
            print(f"[{i+1}/{len(artists)}] {name:<30} SKIP (no URL)")
            continue

        print(f"[{i+1}/{len(artists)}] {name:<30} ", end="", flush=True)
        r = test_tracker(name, url, use_cache=not args.no_cache, verbose=args.verbose)
        results.append(r)

        status = r["status"]
        symbol = {"OK": "✅", "WARN_MANY_UNMATCHED": "⚠️ ", "FAIL_NO_ERAS": "❌", "FAIL_NO_SONGS": "❌", "BANNED": "🚫"}.get(status, "💥")

        if status == "OK":
            ok += 1
        elif status == "BANNED":
            banned += 1
        elif status.startswith("WARN"):
            warn += 1
        elif status.startswith("FAIL"):
            fail += 1
        else:
            err += 1

        print(f"{symbol} {status:<22} eras={r['eras']:<4} songs={r['songs']:<5} versions={r['versions']:<5} "
              f"unmatched={r['unmatched_rows']:<4} fuzzy={r['fuzzy_matched']:<3} {r['time_s']:.1f}s")

        if r["error"]:
            print(f"     ERROR: {r['error']}")

        if args.verbose and r.get("era_details"):
            for line in r["era_details"]:
                print(f"     {line}")

        if args.verbose and r.get("unmatched_samples"):
            print(f"     Unmatched samples:")
            for sample in r["unmatched_samples"][:5]:
                print(f"       {sample}")

    # Summary
    total = len(results)
    print(f"\n{'='*80}")
    print(f"SUMMARY: {total} trackers tested")
    print(f"  ✅ OK:       {ok}")
    print(f"  ⚠️  Warnings: {warn}")
    print(f"  ❌ Failed:   {fail}")
    print(f"  � Banned:   {banned}")
    print(f"  �💥 Errors:   {err}")

    if fail or warn or err:
        print(f"\n--- Problem trackers (excluding banned) ---")
        for r in results:
            if r["status"] not in ("OK", "BANNED"):
                print(f"  {r['name']:<30} {r['status']:<22} eras={r['eras']} songs={r['songs']} "
                      f"unmatched={r['unmatched_rows']}")

    # Dump JSON results for further analysis
    results_path = Path(__file__).resolve().parent.parent.parent / ".cache" / "test_all_results.json"
    results_path.parent.mkdir(exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2))
    print(f"\nDetailed results saved to {results_path}")


if __name__ == "__main__":
    main()
