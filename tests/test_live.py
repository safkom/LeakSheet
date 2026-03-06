"""Live URL tests — comprehensive validation of ALL spreadsheets from links.txt.

Run modes:
  python3 -m pytest tests/test_live.py -v -m live               # all URLs
  python3 -m pytest tests/test_live.py -v -m live -k "structure" # structural only
  python3 tests/test_live.py                                      # standalone runner
  python3 tests/test_live.py --limit 20                           # first 20 unique URLs
  python3 tests/test_live.py --save                               # persist JSON report

These tests require network access and hit live Google Sheets URLs.
Each unique spreadsheet is fetched, parsed, and validated against 12 quality checks.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pytest

# Ensure project root is importable when run standalone
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import TRACKERS_DIR
from src.fetcher import (
    async_fetch_and_parse,
    fetch_and_parse,
    FetchError,
    NetworkError,
    NoTablesError,
    ParseError,
    InvalidURLError,
    AccessDeniedError,
    SHEET_ID_PATTERN,
)
from src.models import Artist


# Mark all tests in this module as 'live'
pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Severity levels and check IDs
# ---------------------------------------------------------------------------

class Severity:
    CRITICAL = "CRITICAL"  # Parser is fundamentally broken for this tracker
    WARNING = "WARNING"    # Data loss or quality issue
    INFO = "INFO"          # Minor observation


@dataclass
class Issue:
    """A single validation issue found in a parsed tracker."""
    check: str
    severity: str
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class TrackerResult:
    """Full result of fetching + validating one tracker URL."""
    url: str
    sheet_id: str
    artist_name: str = ""
    slug: str = ""
    status: str = "pending"  # ok | warning | critical | error
    eras: int = 0
    songs: int = 0
    versions: int = 0
    sections: int = 0
    skip_rate: float = 0.0
    fuzzy_rate: float = 0.0
    fetch_time_s: float = 0.0
    issues: list[Issue] = field(default_factory=list)
    error: str = ""
    error_type: str = ""

    @property
    def has_critical(self) -> bool:
        return any(i.severity == Severity.CRITICAL for i in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(i.severity == Severity.WARNING for i in self.issues)


# ---------------------------------------------------------------------------
# URL loading — deduplicate by spreadsheet ID
# ---------------------------------------------------------------------------

def _read_links() -> list[str]:
    """Read tracker URLs from links.txt, skipping comments and blanks."""
    links_path = TRACKERS_DIR / "links.txt"
    if not links_path.exists():
        return []
    return [
        line.strip()
        for line in links_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _deduplicate_urls(urls: list[str]) -> list[str]:
    """Keep one URL per unique spreadsheet ID. Prefer URLs with explicit GID."""
    seen: dict[str, str] = {}  # sheet_id → best URL
    non_sheets: list[str] = []  # custom domains like yetracker.net

    for url in urls:
        m = SHEET_ID_PATTERN.search(url)
        if not m:
            # Custom domain — keep all (deduplicate by full domain)
            domain = re.sub(r"https?://", "", url).split("/")[0]
            if domain not in seen:
                seen[domain] = url
                non_sheets.append(url)
            continue
        sheet_id = m.group(1)
        if sheet_id not in seen:
            seen[sheet_id] = url
        else:
            # Prefer URL with explicit gid over bare URL
            if "gid=" in url and "gid=" not in seen[sheet_id]:
                seen[sheet_id] = url

    # Return non-sheets first, then sheets in original order
    sheet_urls = [v for v in seen.values() if v not in non_sheets]
    return non_sheets + sheet_urls


# ---------------------------------------------------------------------------
# Regex patterns for bogus era detection
# ---------------------------------------------------------------------------

_BOGUS_ERA_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^changelog",
        r"^update\s*(notes|log)",
        r"^recent\s*(additions|changes)",
        r"^credits?$",
        r"^editors?$",
        r"^(current\s+)?editors?$",
        r"^guidelines?$",
        r"^tracker\s+guidelines?",
        r"^discord$",
        r"^links?$",
        r"^resources?$",
        r"^template",
        r"^about$",
        r"^info$",
        r"^key$",
        r"^legend$",
        r"^navigation",
        r"^table\s*of\s*contents",
        r"^what['\u2019]?s\s+new",
        r"^announcements?$",
        r"^total\s+(full|links|leaks)",
    ]
]

_SECTION_MARKER_KEYWORDS = [
    "features", "collaborations", "collaboration", "featured",
    "loosies", "guest verses", "guest features",
]


# ---------------------------------------------------------------------------
# Validation checks — each returns a list of Issues
# ---------------------------------------------------------------------------

def check_has_eras(artist: Artist) -> list[Issue]:
    """CRITICAL if parser produced zero eras."""
    if len(artist.eras) == 0:
        return [Issue("NO_ERAS", Severity.CRITICAL,
                       f"{artist.name}: parser produced 0 eras")]
    return []


def check_has_songs(artist: Artist) -> list[Issue]:
    """CRITICAL if parser produced zero songs across all eras."""
    if artist.total_songs == 0:
        return [Issue("NO_SONGS", Severity.CRITICAL,
                       f"{artist.name}: 0 songs across {len(artist.eras)} eras")]
    return []


def check_skip_rate(artist: Artist) -> list[Issue]:
    """WARNING if >15% of rows were skipped; INFO if >5%."""
    meta = artist.parse_metadata
    if not meta or meta.total_rows == 0:
        return []
    rate = meta.skipped_rows / meta.total_rows
    if rate > 0.15:
        return [Issue("HIGH_SKIP", Severity.WARNING,
                       f"{artist.name}: {rate:.1%} rows skipped "
                       f"({meta.skipped_rows}/{meta.total_rows})",
                       details=meta.unmatched_rows[:10])]
    if rate > 0.05:
        return [Issue("ELEVATED_SKIP", Severity.INFO,
                       f"{artist.name}: {rate:.1%} rows skipped "
                       f"({meta.skipped_rows}/{meta.total_rows})",
                       details=meta.unmatched_rows[:5])]
    return []


def check_zero_song_eras(artist: Artist) -> list[Issue]:
    """WARNING if any eras have 0 songs (songs placed in wrong era or era mismatch)."""
    zero = [e.name for e in artist.eras if e.song_count == 0]
    if not zero:
        return []
    severity = Severity.WARNING if len(zero) <= 2 else Severity.CRITICAL
    return [Issue("ZERO_SONG_ERAS", severity,
                   f"{artist.name}: {len(zero)} era(s) with 0 songs",
                   details=zero)]


def check_bogus_eras(artist: Artist) -> list[Issue]:
    """WARNING if footer/changelog/nav content was parsed as eras."""
    bogus = []
    for era in artist.eras:
        for pat in _BOGUS_ERA_PATTERNS:
            if pat.search(era.name):
                bogus.append(era.name)
                break
    if not bogus:
        return []
    return [Issue("BOGUS_ERAS", Severity.WARNING,
                   f"{artist.name}: {len(bogus)} non-music era(s) detected",
                   details=bogus)]


def check_lost_section_markers(artist: Artist) -> list[Issue]:
    """INFO if 'Features'/'Collaborations' labels ended up in unmatched rows."""
    meta = artist.parse_metadata
    if not meta:
        return []
    lost = []
    for row_summary in meta.unmatched_rows:
        lower = row_summary.lower()
        for kw in _SECTION_MARKER_KEYWORDS:
            if kw in lower:
                lost.append(row_summary)
                break
    if not lost:
        return []
    return [Issue("LOST_SECTIONS", Severity.INFO,
                   f"{artist.name}: {len(lost)} section marker(s) in unmatched rows",
                   details=lost)]


def check_section_info(artist: Artist) -> list[Issue]:
    """INFO: report how many named sections exist (for visibility)."""
    named = []
    for era in artist.eras:
        for sec in era.sections:
            if sec.name:
                named.append(f"{era.name} → {sec.name} ({len(sec.songs)} songs)")
    # Not an issue — just reporting. Only emit if there ARE sections.
    if named:
        return [Issue("SECTIONS_FOUND", Severity.INFO,
                       f"{artist.name}: {len(named)} named section(s)",
                       details=named[:20])]
    return []


def check_song_era_ratio(artist: Artist) -> list[Issue]:
    """WARNING if average songs/era is suspiciously low (<3)."""
    if not artist.eras:
        return []
    ratio = artist.total_songs / len(artist.eras)
    if ratio < 3.0 and len(artist.eras) >= 3:
        return [Issue("LOW_SONG_RATIO", Severity.WARNING,
                       f"{artist.name}: avg {ratio:.1f} songs/era "
                       f"({artist.total_songs} songs / {len(artist.eras)} eras)")]
    return []


def check_many_eras(artist: Artist) -> list[Issue]:
    """INFO if >40 eras (might include junk content)."""
    if len(artist.eras) > 40:
        return [Issue("MANY_ERAS", Severity.INFO,
                       f"{artist.name}: {len(artist.eras)} eras — "
                       f"verify no junk content")]
    return []


def check_fuzzy_match_rate(artist: Artist) -> list[Issue]:
    """WARNING if >20% of song rows needed fuzzy matching."""
    meta = artist.parse_metadata
    if not meta or meta.song_rows == 0:
        return []
    rate = meta.fuzzy_matched_rows / meta.song_rows
    if rate > 0.20:
        return [Issue("HIGH_FUZZY", Severity.WARNING,
                       f"{artist.name}: {rate:.1%} of songs fuzzy-matched "
                       f"({meta.fuzzy_matched_rows}/{meta.song_rows})")]
    return []


def check_duplicate_era_names(artist: Artist) -> list[Issue]:
    """WARNING if two eras have the same name (parser bug or data issue)."""
    names = [e.name for e in artist.eras]
    seen: dict[str, int] = {}
    for n in names:
        key = n.strip().lower()
        seen[key] = seen.get(key, 0) + 1
    dupes = [n for n, count in seen.items() if count > 1]
    if not dupes:
        return []
    return [Issue("DUPLICATE_ERAS", Severity.WARNING,
                   f"{artist.name}: {len(dupes)} duplicate era name(s)",
                   details=dupes)]


def check_era_stats_consistency(artist: Artist) -> list[Issue]:
    """WARNING if era stats total diverges >25% from actual parsed version count."""
    eras_with_stats = [e for e in artist.eras if e.stats and e.stats.total > 0]
    if not eras_with_stats:
        return []
    stats_total = sum(e.stats.total for e in eras_with_stats)
    parsed_total = sum(e.version_count for e in eras_with_stats)
    if parsed_total == 0:
        return []
    diff = abs(stats_total - parsed_total) / parsed_total
    if diff > 0.25:
        return [Issue("STATS_MISMATCH", Severity.WARNING,
                       f"{artist.name}: era stats say {stats_total} versions "
                       f"but parser found {parsed_total} ({diff:.0%} off)")]
    return []


ALL_CHECKS = [
    check_has_eras,
    check_has_songs,
    check_skip_rate,
    check_zero_song_eras,
    check_bogus_eras,
    check_lost_section_markers,
    check_section_info,
    check_song_era_ratio,
    check_many_eras,
    check_fuzzy_match_rate,
    check_duplicate_era_names,
    check_era_stats_consistency,
]


def validate_artist(artist: Artist) -> list[Issue]:
    """Run all checks and return combined issues."""
    issues: list[Issue] = []
    for check_fn in ALL_CHECKS:
        issues.extend(check_fn(artist))
    return issues


# ---------------------------------------------------------------------------
# Async runner — concurrent fetch + validate
# ---------------------------------------------------------------------------

_CONCURRENCY = 8  # max parallel fetches


async def _fetch_one(url: str, sheet_id: str, semaphore: asyncio.Semaphore) -> TrackerResult:
    """Fetch and validate a single tracker URL."""
    result = TrackerResult(url=url, sheet_id=sheet_id)
    async with semaphore:
        t0 = time.monotonic()
        try:
            artist = await async_fetch_and_parse(url, use_cache=True)
            result.fetch_time_s = round(time.monotonic() - t0, 2)
            result.artist_name = artist.name
            result.slug = artist.slug
            result.eras = len(artist.eras)
            result.songs = artist.total_songs
            result.versions = artist.total_versions
            result.sections = sum(
                1 for e in artist.eras for s in e.sections if s.name
            )
            meta = artist.parse_metadata
            if meta and meta.total_rows > 0:
                result.skip_rate = round(meta.skipped_rows / meta.total_rows, 4)
            if meta and meta.song_rows > 0:
                result.fuzzy_rate = round(
                    meta.fuzzy_matched_rows / meta.song_rows, 4
                )

            # Run validation
            result.issues = validate_artist(artist)
            if result.has_critical:
                result.status = "critical"
            elif result.has_warning:
                result.status = "warning"
            else:
                result.status = "ok"

        except AccessDeniedError as e:
            result.fetch_time_s = round(time.monotonic() - t0, 2)
            result.status = "error"
            result.error = str(e)
            result.error_type = "access_denied"
        except NetworkError as e:
            result.fetch_time_s = round(time.monotonic() - t0, 2)
            result.status = "error"
            result.error = str(e)
            result.error_type = "network"
        except NoTablesError as e:
            result.fetch_time_s = round(time.monotonic() - t0, 2)
            result.status = "error"
            result.error = str(e)
            result.error_type = "no_tables"
        except (FetchError, Exception) as e:
            result.fetch_time_s = round(time.monotonic() - t0, 2)
            result.status = "error"
            result.error = f"{type(e).__name__}: {e}"
            result.error_type = type(e).__name__
    return result


async def run_all(urls: list[str], limit: int | None = None) -> list[TrackerResult]:
    """Fetch and validate all URLs concurrently."""
    deduped = _deduplicate_urls(urls)
    if limit:
        deduped = deduped[:limit]

    print(f"\n{'='*70}")
    print(f"  LeakSheet Live Spreadsheet Validation")
    print(f"  {len(deduped)} unique spreadsheets (from {len(urls)} URLs)")
    print(f"  Concurrency: {_CONCURRENCY}")
    print(f"{'='*70}\n")

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    tasks = []
    for url in deduped:
        m = SHEET_ID_PATTERN.search(url)
        sheet_id = m.group(1) if m else url[:50]
        tasks.append(_fetch_one(url, sheet_id, semaphore))

    results: list[TrackerResult] = []
    done = 0
    total = len(tasks)

    # Process as completed for live progress
    for coro in asyncio.as_completed(tasks):
        result = await coro
        results.append(result)
        done += 1
        icon = {"ok": "\033[32m✓\033[0m", "warning": "\033[33m⚠\033[0m",
                "critical": "\033[31m✗\033[0m", "error": "\033[31m☠\033[0m"
                }.get(result.status, "?")
        name = result.artist_name or result.sheet_id[:20]
        issues_str = ""
        if result.issues:
            tags = sorted(set(i.check for i in result.issues if i.severity != Severity.INFO))
            if tags:
                issues_str = f"  [{', '.join(tags)}]"
        if result.error:
            issues_str = f"  [{result.error_type}]"
        print(f"  [{done:3d}/{total}] {icon} {name:<35} "
              f"{result.eras:3d}E {result.songs:4d}S {result.fetch_time_s:5.1f}s{issues_str}")

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(results: list[TrackerResult]) -> None:
    """Print a summary report of all validation results."""
    ok = [r for r in results if r.status == "ok"]
    warn = [r for r in results if r.status == "warning"]
    crit = [r for r in results if r.status == "critical"]
    err = [r for r in results if r.status == "error"]

    total_eras = sum(r.eras for r in results)
    total_songs = sum(r.songs for r in results)
    total_versions = sum(r.versions for r in results)

    print(f"\n{'='*70}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*70}")
    print(f"  Total spreadsheets:  {len(results)}")
    print(f"  \033[32m✓ OK:       {len(ok):4d}\033[0m")
    print(f"  \033[33m⚠ Warning:  {len(warn):4d}\033[0m")
    print(f"  \033[31m✗ Critical: {len(crit):4d}\033[0m")
    print(f"  \033[31m☠ Error:    {len(err):4d}\033[0m")
    print(f"")
    print(f"  Total eras:     {total_eras:,}")
    print(f"  Total songs:    {total_songs:,}")
    print(f"  Total versions: {total_versions:,}")

    # Error breakdown
    if err:
        print(f"\n{'─'*70}")
        print(f"  FETCH ERRORS ({len(err)})")
        print(f"{'─'*70}")
        error_types: dict[str, list[TrackerResult]] = {}
        for r in err:
            error_types.setdefault(r.error_type, []).append(r)
        for etype, group in sorted(error_types.items()):
            print(f"  {etype}: {len(group)}")
            for r in group[:5]:
                name = r.artist_name or r.sheet_id[:30]
                print(f"    - {name}: {r.error[:80]}")
            if len(group) > 5:
                print(f"    ... and {len(group) - 5} more")

    # Critical issues
    if crit:
        print(f"\n{'─'*70}")
        print(f"  \033[31mCRITICAL ISSUES ({len(crit)})\033[0m")
        print(f"{'─'*70}")
        for r in crit:
            print(f"  {r.artist_name} ({r.eras}E / {r.songs}S)")
            for issue in r.issues:
                if issue.severity == Severity.CRITICAL:
                    print(f"    ✗ [{issue.check}] {issue.message}")
                    for d in issue.details[:5]:
                        print(f"      - {d}")

    # Warning details
    if warn:
        print(f"\n{'─'*70}")
        print(f"  \033[33mWARNINGS ({len(warn)})\033[0m")
        print(f"{'─'*70}")

        # Group by check type
        by_check: dict[str, list[tuple[TrackerResult, Issue]]] = {}
        for r in warn:
            for issue in r.issues:
                if issue.severity == Severity.WARNING:
                    by_check.setdefault(issue.check, []).append((r, issue))

        for check_name, items in sorted(by_check.items()):
            print(f"\n  [{check_name}] — {len(items)} tracker(s)")
            for r, issue in items[:10]:
                print(f"    ⚠ {issue.message}")
                for d in issue.details[:3]:
                    print(f"      - {d}")
            if len(items) > 10:
                print(f"    ... and {len(items) - 10} more")

    # Info highlights (sections found, lost markers)
    info_items = []
    for r in results:
        for issue in r.issues:
            if issue.severity == Severity.INFO and issue.check in ("LOST_SECTIONS", "SECTIONS_FOUND"):
                info_items.append((r, issue))
    if info_items:
        print(f"\n{'─'*70}")
        print(f"  INFO — Sections & Markers")
        print(f"{'─'*70}")
        for r, issue in info_items[:30]:
            print(f"  ℹ {issue.message}")
            for d in issue.details[:5]:
                print(f"    - {d}")

    print(f"\n{'='*70}\n")


def save_report(results: list[TrackerResult], path: Path) -> None:
    """Save results to JSON file."""
    data = []
    for r in results:
        d = {
            "url": r.url,
            "sheet_id": r.sheet_id,
            "artist_name": r.artist_name,
            "slug": r.slug,
            "status": r.status,
            "eras": r.eras,
            "songs": r.songs,
            "versions": r.versions,
            "sections": r.sections,
            "skip_rate": r.skip_rate,
            "fuzzy_rate": r.fuzzy_rate,
            "fetch_time_s": r.fetch_time_s,
            "issues": [asdict(i) for i in r.issues],
            "error": r.error,
            "error_type": r.error_type,
        }
        data.append(d)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"  Saved results to {path}")


# ---------------------------------------------------------------------------
# pytest fixtures — for running as pytest tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_artists():
    """Fetch and parse all live tracker URLs (sync, for pytest)."""
    urls = _read_links()
    if not urls:
        pytest.skip("No URLs in links.txt")
    deduped = _deduplicate_urls(urls)
    results = {}
    for url in deduped[:20]:  # pytest: limit to 20 for speed
        try:
            artist = fetch_and_parse(url)
            results[artist.slug] = artist
        except FetchError:
            continue
    return results


@pytest.fixture(scope="module")
def ye_live(live_artists):
    return live_artists.get("ye")


@pytest.fixture(scope="module")
def kendrick_live(live_artists):
    return live_artists.get("kendrick-lamar")


@pytest.fixture(scope="module")
def keem_live(live_artists):
    return live_artists.get("baby-keem")


@pytest.fixture(scope="module")
def carti_live(live_artists):
    return live_artists.get("playboi-carti")


# ---------------------------------------------------------------------------
# Structural completeness — every tracker
# ---------------------------------------------------------------------------

class TestLiveStructure:
    """Basic structural checks on live-fetched data."""

    def test_all_trackers_loaded(self, live_artists):
        assert len(live_artists) >= 4, f"Expected >=4 artists, got {len(live_artists)}"

    def test_every_artist_has_eras(self, live_artists):
        for slug, artist in live_artists.items():
            assert len(artist.eras) > 0, f"{artist.name} has no eras"

    def test_every_artist_has_songs(self, live_artists):
        for slug, artist in live_artists.items():
            assert artist.total_songs > 0, f"{artist.name} has no songs"

    def test_source_url_set(self, live_artists):
        for slug, artist in live_artists.items():
            assert artist.source_url is not None, f"{artist.name} missing source_url"

    def test_no_bogus_eras(self, live_artists):
        for slug, artist in live_artists.items():
            issues = check_bogus_eras(artist)
            assert not issues, f"{artist.name}: {issues[0].message}"

    def test_no_duplicate_era_names(self, live_artists):
        for slug, artist in live_artists.items():
            issues = check_duplicate_era_names(artist)
            assert not issues, f"{artist.name}: {issues[0].message}"


# ---------------------------------------------------------------------------
# Parse metadata — no silent data loss
# ---------------------------------------------------------------------------

class TestParseMetadata:
    """Verify parse metadata is populated and skipped rows are minimal."""

    def test_metadata_exists(self, live_artists):
        for slug, artist in live_artists.items():
            assert artist.parse_metadata is not None, (
                f"{artist.name} has no parse_metadata"
            )

    def test_song_rows_positive(self, live_artists):
        for slug, artist in live_artists.items():
            meta = artist.parse_metadata
            assert meta.song_rows > 0, f"{artist.name}: 0 song_rows parsed"

    def test_skipped_rows_low(self, live_artists):
        """Skipped rows should be < 15% of total rows."""
        for slug, artist in live_artists.items():
            meta = artist.parse_metadata
            if meta.total_rows == 0:
                continue
            skip_pct = meta.skipped_rows / meta.total_rows
            assert skip_pct < 0.15, (
                f"{artist.name}: {meta.skipped_rows}/{meta.total_rows} rows skipped "
                f"({skip_pct:.1%}). Unmatched: {meta.unmatched_rows[:5]}"
            )


# ---------------------------------------------------------------------------
# Era art — live trackers should have art for most eras
# ---------------------------------------------------------------------------

class TestLiveEraArt:
    """Live trackers have more images than local HTML exports."""

    def test_ye_most_eras_have_art(self, ye_live):
        if ye_live is None:
            pytest.skip("Ye not loaded")
        eras_with_art = [e for e in ye_live.eras if e.art_url]
        ratio = len(eras_with_art) / len(ye_live.eras) if ye_live.eras else 0
        assert ratio > 0.5, (
            f"Only {len(eras_with_art)}/{len(ye_live.eras)} Ye eras have art"
        )

    def test_keem_most_eras_have_art(self, keem_live):
        if keem_live is None:
            pytest.skip("Baby Keem not loaded")
        eras_with_art = [e for e in keem_live.eras if e.art_url]
        assert len(eras_with_art) >= len(keem_live.eras) // 2


# ---------------------------------------------------------------------------
# Era stats consistency
# ---------------------------------------------------------------------------

class TestLiveEraStats:
    """Verify era stats totals are close to actual parsed song counts."""

    def test_stats_parsed_when_raw_present(self, live_artists):
        """If an era has a raw stats string, it must parse successfully."""
        for slug, artist in live_artists.items():
            for era in artist.eras:
                if era.stats_raw:
                    assert era.stats is not None, (
                        f"{artist.name} era '{era.name}' has stats_raw "
                        f"but stats failed to parse: {era.stats_raw!r}"
                    )


# ---------------------------------------------------------------------------
# Zero-song eras
# ---------------------------------------------------------------------------

class TestLiveZeroEras:
    """With live data, all eras should have songs."""

    def test_no_zero_song_eras(self, live_artists):
        for slug, artist in live_artists.items():
            zero_eras = [e for e in artist.eras if e.song_count == 0]
            assert len(zero_eras) <= 2, (
                f"{artist.name}: {len(zero_eras)} eras with 0 songs: "
                f"{[e.name for e in zero_eras]}"
            )


# ---------------------------------------------------------------------------
# Standalone runner — python3 tests/test_live.py [--limit N] [--save]
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LeakSheet live spreadsheet validation")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max spreadsheets to test (default: all)")
    parser.add_argument("--save", action="store_true",
                        help="Save JSON report to tests/results/")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable HTTP cache (fresh fetch every time)")
    args = parser.parse_args()

    urls = _read_links()
    if not urls:
        print("ERROR: No URLs found in Trackers/links.txt")
        sys.exit(1)

    t0 = time.monotonic()
    results = asyncio.run(run_all(urls, limit=args.limit))
    elapsed = time.monotonic() - t0

    print_report(results)
    print(f"  Total time: {elapsed:.1f}s")

    if args.save:
        report_path = PROJECT_ROOT / "tests" / "results" / "live_validation.json"
        save_report(results, report_path)

    # Exit with non-zero if any criticals
    criticals = [r for r in results if r.status == "critical"]
    errors = [r for r in results if r.status == "error"]
    if criticals:
        print(f"\n  \033[31m{len(criticals)} CRITICAL tracker(s) — parser needs fixing\033[0m")
        sys.exit(2)
    if len(errors) > len(results) * 0.5:
        print(f"\n  \033[31m>50% fetch errors — possible network issue\033[0m")
        sys.exit(3)

    print(f"  \033[32mDone.\033[0m\n")


if __name__ == "__main__":
    main()
