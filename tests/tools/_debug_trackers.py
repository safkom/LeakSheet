#!/usr/bin/env python3
"""Debug specific trackers to find missing eras."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx
from src.fetcher import fetch_sheet_html
from src.parser import extract_table, ERA_STATS_PATTERN, _era_match_key, _looks_like_era_name, _Cell

URLS = [
    ("Drake", "https://docs.google.com/spreadsheets/d/1v55XAPLzw1iuWxH1OQKajCIYPhW2BXcLoV4mXDZ55DI/edit?gid=755606328#gid=755606328"),
    ("Lil Uzi", "https://docs.google.com/spreadsheets/d/1zqqdIds1iwnx4lh29iF1IlraeuqfGhxH9qLNlWOnryo/edit?gid=1160569231#gid=1160569231"),
]


def analyze_tracker(name, url):
    print(f"\n{'='*80}")
    print(f"ANALYZING: {name}")
    print(f"URL: {url}")
    print(f"{'='*80}")

    html, title = fetch_sheet_html(url, use_cache=True)
    print(f"Title: {title}")

    parser = _SheetHTMLParser()
    parser.feed(html)
    rows = parser.rows
    print(f"Total HTML rows: {len(rows)}")

    # Detect header row
    print(f"\nRow 0 (header): {' | '.join(c.text.strip()[:20] for c in rows[0][:10])}")

    # Find all era header rows (rows where cell0 matches ERA_STATS_PATTERN)
    era_headers = []
    era_col_values = {}  # unique era col values -> count

    for i, row in enumerate(rows[1:], start=1):
        if not row:
            continue
        cell0 = row[0].text.strip() if row[0].text else ""
        cell1 = row[1].text.strip() if len(row) > 1 and row[1].text else ""

        if ERA_STATS_PATTERN.search(cell0):
            era_headers.append((i, cell0[:100], cell1[:100]))
        elif cell0:
            era_col_values[cell0] = era_col_values.get(cell0, 0) + 1

    print(f"\n--- ERA HEADERS (rows with stats in col0) [{len(era_headers)}] ---")
    for idx, stats, era_name in era_headers:
        print(f"  Row {idx}: name={era_name!r}  stats={stats[:60]!r}")

    print(f"\n--- UNIQUE ERA COL VALUES (col0 of song rows) [{len(era_col_values)}] ---")
    for val, count in sorted(era_col_values.items(), key=lambda x: -x[1]):
        key = _era_match_key(val)
        is_plausible = _looks_like_era_name(val)
        print(f"  {count:4d}x  key={key!r:50s}  plausible={is_plausible}  raw={val[:80]!r}")

    # Check which era col values DON'T have a matching header
    header_keys = set()
    for _, stats, era_name in era_headers:
        k = _era_match_key(era_name)
        if k:
            header_keys.add(k)

    print(f"\n--- UNMATCHED ERA COL VALUES (no matching header) ---")
    for val, count in sorted(era_col_values.items(), key=lambda x: -x[1]):
        key = _era_match_key(val)
        if key and key not in header_keys:
            print(f"  {count:4d}x  key={key!r:50s}  raw={val[:80]!r}")


if __name__ == "__main__":
    for name, url in URLS:
        analyze_tracker(name, url)
