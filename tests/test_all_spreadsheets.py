#!/usr/bin/env python3
"""Test all spreadsheets from artists.ndjson against the parser.

Usage:
    # Test all artists (slow — 486 spreadsheets):
    python tests/test_all_spreadsheets.py

    # Test only 'best' trackers (curated, higher quality):
    python tests/test_all_spreadsheets.py --best

    # Test a specific artist:
    python tests/test_all_spreadsheets.py --artist "Kendrick Lamar"

    # Test first N artists:
    python tests/test_all_spreadsheets.py --limit 10

    # Resume from a previous run (skips already-tested artists):
    python tests/test_all_spreadsheets.py --resume

    # Increase concurrency:
    python tests/test_all_spreadsheets.py --workers 8

Results are saved to tests/results/spreadsheet_test_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetcher import (
    async_fetch_and_parse,
    fetch_sheet_html,
    AccessDeniedError,
    InvalidURLError,
    NetworkError,
    NoTablesError,
)
from src.parser import extract_table, detect_columns
from src.models import Artist


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


@dataclass
class Issue:
    severity: str  # "error", "warn", "info"
    message: str


@dataclass
class TestResult:
    name: str
    url: str
    status: str = Status.OK
    eras: int = 0
    songs: int = 0
    versions: int = 0
    columns_detected: list[str] = field(default_factory=list)
    skipped_rows: int = 0
    total_rows: int = 0
    skip_pct: float = 0.0
    zero_song_eras: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    error: str | None = None
    elapsed_s: float = 0.0
    is_best: bool = False


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def validate_artist(artist: Artist, name: str, url: str, is_best: bool) -> TestResult:
    """Run all validation checks on a parsed artist."""
    result = TestResult(name=name, url=url, is_best=is_best)
    issues: list[Issue] = []

    # Basic counts
    result.eras = len(artist.eras)
    result.songs = artist.total_songs
    result.versions = artist.total_versions

    # Parse metadata
    meta = artist.parse_metadata
    if meta:
        result.skipped_rows = meta.skipped_rows
        result.total_rows = meta.total_rows
        result.skip_pct = (
            meta.skipped_rows / meta.total_rows * 100
            if meta.total_rows > 0 else 0
        )

    # Check: has eras
    if result.eras == 0:
        issues.append(Issue("error", "No eras parsed"))
        result.status = Status.FAIL
        return _finalize(result, issues)

    # Check: has songs
    if result.songs == 0:
        issues.append(Issue("error", "No songs parsed (eras exist but all empty)"))
        result.status = Status.FAIL
        return _finalize(result, issues)

    # Check: skipped rows
    if result.skip_pct > 20:
        issues.append(Issue("error", f"High skip rate: {result.skip_pct:.1f}% ({result.skipped_rows}/{result.total_rows})"))
        result.status = Status.FAIL
    elif result.skip_pct > 5:
        issues.append(Issue("warn", f"Elevated skip rate: {result.skip_pct:.1f}% ({result.skipped_rows}/{result.total_rows})"))
        if result.status == Status.OK:
            result.status = Status.WARN

    # Check: zero-song eras
    zero_eras = [e.name for e in artist.eras if e.song_count == 0]
    result.zero_song_eras = zero_eras
    if len(zero_eras) > 3:
        issues.append(Issue("warn", f"{len(zero_eras)} eras with 0 songs: {zero_eras[:5]}"))
        if result.status == Status.OK:
            result.status = Status.WARN

    # Check: songs per era ratio (too few songs = likely bad parse)
    avg_songs = result.songs / result.eras if result.eras > 0 else 0
    if avg_songs < 1.0 and result.eras > 2:
        issues.append(Issue("warn", f"Very few songs per era: {avg_songs:.1f} avg"))
        if result.status == Status.OK:
            result.status = Status.WARN

    # Check: unmatched rows (first few for diagnostics)
    if meta and meta.unmatched_rows:
        first_unmatched = meta.unmatched_rows[:3]
        issues.append(Issue("info", f"Sample unmatched rows: {first_unmatched}"))

    return _finalize(result, issues)


def _finalize(result: TestResult, issues: list[Issue]) -> TestResult:
    result.issues = [{"severity": i.severity, "message": i.message} for i in issues]
    return result


# ---------------------------------------------------------------------------
# Load artists from NDJSON
# ---------------------------------------------------------------------------

def load_artists(
    ndjson_path: Path,
    *,
    best_only: bool = False,
    artist_filter: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Load artist entries from NDJSON file with optional filters."""
    artists = []
    with open(ndjson_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Skip non-spreadsheet URLs (Google Docs, etc.)
            url = entry.get("url", "")
            if "docs.google.com/document" in url:
                continue

            if best_only and not entry.get("best", False):
                continue

            if artist_filter:
                name = entry.get("name", "")
                if artist_filter.lower() not in name.lower():
                    continue

            artists.append(entry)

    if limit:
        artists = artists[:limit]

    return artists


# ---------------------------------------------------------------------------
# Async test runner
# ---------------------------------------------------------------------------

async def test_one(
    entry: dict,
    semaphore: asyncio.Semaphore,
    timeout: float = 120.0,
) -> TestResult:
    """Test a single artist spreadsheet."""
    name = entry["name"]
    url = entry["url"]
    is_best = entry.get("best", False)

    # Detect abandoned trackers (links_work=0 + updated=0)
    is_abandoned = entry.get("links_work", 1) == 0 and entry.get("updated", 1) == 0

    async with semaphore:
        t0 = time.monotonic()
        try:
            artist = await async_fetch_and_parse(
                url,
                artist_name=name,
                timeout=timeout,
                use_cache=True,
                cache_ttl=86400,  # 24h cache for mass testing
            )
            result = validate_artist(artist, name, url, is_best)

            # Try to get column info from cached HTML
            try:
                html, _ = fetch_sheet_html(
                    url, timeout=10, use_cache=True, cache_ttl=86400,
                )
                rows = extract_table(html)
                if rows:
                    col_map = detect_columns(rows[0])
                    result.columns_detected = sorted(col_map.keys())
            except Exception:
                pass  # Column detection is best-effort
        except AccessDeniedError as e:
            result = TestResult(
                name=name, url=url, status=Status.SKIP,
                error=f"Access denied: {e}", is_best=is_best,
            )
        except InvalidURLError as e:
            result = TestResult(
                name=name, url=url, status=Status.ERROR,
                error=f"Invalid URL: {e}", is_best=is_best,
            )
        except NetworkError as e:
            # Downgrade network errors on abandoned trackers to SKIP
            status = Status.SKIP if is_abandoned else Status.ERROR
            result = TestResult(
                name=name, url=url, status=status,
                error=f"Network error: {e}", is_best=is_best,
            )
        except NoTablesError as e:
            status = Status.SKIP if is_abandoned else Status.FAIL
            result = TestResult(
                name=name, url=url, status=status,
                error=f"No tables found: {e}", is_best=is_best,
            )
        except Exception as e:
            result = TestResult(
                name=name, url=url, status=Status.ERROR,
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                is_best=is_best,
            )

        result.elapsed_s = round(time.monotonic() - t0, 2)
        return result


async def run_all(
    artists: list[dict],
    *,
    workers: int = 4,
    timeout: float = 120.0,
    prev_results: dict[str, TestResult] | None = None,
) -> list[TestResult]:
    """Run tests for all artists concurrently."""
    semaphore = asyncio.Semaphore(workers)
    results: list[TestResult] = []
    total = len(artists)

    # Status counters
    counts = {s: 0 for s in Status}
    done = 0

    async def run_and_report(entry: dict) -> TestResult:
        nonlocal done

        # Skip if already tested (resume mode)
        if prev_results and entry["name"] in prev_results:
            r = prev_results[entry["name"]]
            done += 1
            return r

        r = await test_one(entry, semaphore, timeout)
        done += 1
        counts[Status(r.status)] += 1

        # Progress indicator
        icon = {
            Status.OK: "\033[32m+\033[0m",
            Status.WARN: "\033[33m~\033[0m",
            Status.FAIL: "\033[31mX\033[0m",
            Status.ERROR: "\033[31m!\033[0m",
            Status.SKIP: "\033[90m-\033[0m",
        }.get(Status(r.status), "?")

        summary = f"  {r.eras}E/{r.songs}S" if r.eras > 0 else ""
        err_msg = f" — {r.error[:80]}" if r.error else ""
        skip_msg = f" skip:{r.skip_pct:.0f}%" if r.skip_pct > 5 else ""

        print(f"[{icon}] {done:3d}/{total} {r.name:<35s} {r.elapsed_s:5.1f}s{summary}{skip_msg}{err_msg}")

        return r

    tasks = [run_and_report(entry) for entry in artists]
    results = await asyncio.gather(*tasks)
    return list(results)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_summary(results: list[TestResult]) -> None:
    """Print a summary of test results."""
    counts = {s: 0 for s in Status}
    for r in results:
        counts[Status(r.status)] += 1

    total = len(results)
    print("\n" + "=" * 70)
    print(f"RESULTS: {total} spreadsheets tested")
    print(f"  OK:    {counts[Status.OK]:4d}  ({counts[Status.OK]/total*100:.0f}%)" if total else "")
    print(f"  WARN:  {counts[Status.WARN]:4d}  ({counts[Status.WARN]/total*100:.0f}%)" if total else "")
    print(f"  FAIL:  {counts[Status.FAIL]:4d}  ({counts[Status.FAIL]/total*100:.0f}%)" if total else "")
    print(f"  ERROR: {counts[Status.ERROR]:4d}  ({counts[Status.ERROR]/total*100:.0f}%)" if total else "")
    print(f"  SKIP:  {counts[Status.SKIP]:4d}  ({counts[Status.SKIP]/total*100:.0f}%)" if total else "")
    print("=" * 70)

    # Show failures
    failures = [r for r in results if r.status in (Status.FAIL, Status.ERROR)]
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for r in failures:
            print(f"  [{r.status}] {r.name}")
            if r.error:
                print(f"         {r.error[:120]}")
            for issue in r.issues:
                if issue["severity"] in ("error", "warn"):
                    print(f"         {issue['severity']}: {issue['message'][:120]}")

    # Show warnings
    warnings = [r for r in results if r.status == Status.WARN]
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for r in warnings:
            for issue in r.issues:
                if issue["severity"] == "warn":
                    print(f"  {r.name}: {issue['message'][:120]}")

    # Column detection analysis: find trackers with unusual column layouts
    known_columns = {"era", "name", "notes", "track_length", "file_date",
                     "leak_date", "available_length", "quality", "links",
                     "type", "date_of_recording", "streaming"}
    unusual = [r for r in results if r.columns_detected
               and not set(r.columns_detected).issubset(known_columns)]
    if unusual:
        print(f"\nUNUSUAL COLUMNS ({len(unusual)}):")
        for r in unusual:
            extra = set(r.columns_detected) - known_columns
            print(f"  {r.name}: {extra}")


def save_results(results: list[TestResult], path: Path) -> None:
    """Save results to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(r) for r in results]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nResults saved to {path}")


def load_prev_results(path: Path) -> dict[str, TestResult]:
    """Load previous results for resume mode."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        results = {}
        for entry in data:
            if entry.get("status") in (Status.OK, Status.WARN):
                r = TestResult(**{k: v for k, v in entry.items()
                                  if k in TestResult.__dataclass_fields__})
                results[r.name] = r
        return results
    except (json.JSONDecodeError, Exception):
        return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Test all tracker spreadsheets")
    parser.add_argument("--ndjson", type=Path,
                        default=Path(__file__).resolve().parent.parent / "Trackers" / "artists.ndjson",
                        help="Path to artists.ndjson file")
    parser.add_argument("--best", action="store_true",
                        help="Only test 'best' trackers")
    parser.add_argument("--artist", type=str, default=None,
                        help="Filter by artist name (substring match)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Test only first N artists")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of concurrent workers")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="HTTP timeout per request in seconds")
    parser.add_argument("--resume", action="store_true",
                        help="Skip artists that passed in previous run")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parent / "results" / "spreadsheet_test_results.json",
                        help="Output path for results JSON")
    args = parser.parse_args()

    # Allow fallback to the downloads path
    ndjson_path = args.ndjson
    if not ndjson_path.exists():
        alt = Path.home() / "Downloads" / "artists.ndjson"
        if alt.exists():
            ndjson_path = alt
        else:
            print(f"Error: {ndjson_path} not found")
            sys.exit(1)

    # Load artists
    artists = load_artists(
        ndjson_path,
        best_only=args.best,
        artist_filter=args.artist,
        limit=args.limit,
    )

    if not artists:
        print("No artists match the filter criteria.")
        sys.exit(0)

    print(f"Testing {len(artists)} spreadsheets (workers={args.workers}, timeout={args.timeout}s)")
    print("-" * 70)

    # Load previous results for resume mode
    prev_results = load_prev_results(args.output) if args.resume else None
    if prev_results:
        print(f"Resuming: {len(prev_results)} previously passed results loaded")

    # Run tests
    t0 = time.monotonic()
    results = asyncio.run(run_all(
        artists,
        workers=args.workers,
        timeout=args.timeout,
        prev_results=prev_results,
    ))
    elapsed = time.monotonic() - t0

    # Report
    print_summary(results)
    print(f"\nTotal time: {elapsed:.1f}s")

    # Save results
    save_results(results, args.output)

    # Exit code: 1 if any failures
    failures = [r for r in results if r.status == Status.FAIL]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
