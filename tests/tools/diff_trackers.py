#!/usr/bin/env python3
"""Compare column layouts across all tracker files.

Usage:
    python -m tests.tools.diff_trackers

Shows the detected column mappings and highlights differences between trackers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import discover_trackers, TRACKERS_DIR
from src.parser import extract_table, detect_columns


def main() -> None:
    trackers = discover_trackers(TRACKERS_DIR)
    if not trackers:
        print("No trackers found in", TRACKERS_DIR)
        return

    all_columns: dict[str, dict[str, int]] = {}
    all_headers: dict[str, list[str]] = {}

    for artist_name, sheet_path in trackers:
        html = sheet_path.read_text(encoding="utf-8")
        rows = extract_table(html)
        if not rows:
            print(f"WARNING: No rows found in {artist_name}")
            continue

        col_map = detect_columns(rows[0])
        header_texts = [cell.text[:40] for cell in rows[0]]

        all_columns[artist_name] = col_map
        all_headers[artist_name] = header_texts

    # Print raw headers
    print("RAW HEADER COLUMNS")
    print("=" * 80)
    for name, headers in all_headers.items():
        print(f"\n  {name}:")
        for i, h in enumerate(headers):
            print(f"    [{i}] {h}")

    # Print detected mappings
    print(f"\n\nDETECTED COLUMN MAPPINGS")
    print("=" * 80)

    # Collect all canonical fields
    all_fields: set[str] = set()
    for col_map in all_columns.values():
        all_fields.update(col_map.keys())

    # Print as a table
    sorted_fields = sorted(all_fields)
    artist_names = list(all_columns.keys())

    # Header
    print(f"\n  {'Field':<22}", end="")
    for name in artist_names:
        short = name[:12]
        print(f"  {short:<14}", end="")
    print()
    print(f"  {'-'*22}", end="")
    for _ in artist_names:
        print(f"  {'-'*14}", end="")
    print()

    # Rows
    for field in sorted_fields:
        print(f"  {field:<22}", end="")
        values = []
        for name in artist_names:
            idx = all_columns[name].get(field)
            val = f"col {idx}" if idx is not None else "  --"
            values.append(val)
            print(f"  {val:<14}", end="")
        print()

        # Highlight if values differ
        unique = set(v for v in values if v != "  --")
        if len(unique) > 1:
            print(f"  {'  ⚠️  DIFFERS':<22}")

    # Summary
    print(f"\n\nSUMMARY")
    print("=" * 80)
    for name in artist_names:
        fields = all_columns[name]
        print(f"  {name}: {len(fields)} columns detected")
        missing = all_fields - set(fields.keys())
        if missing:
            print(f"    Missing: {', '.join(sorted(missing))}")


if __name__ == "__main__":
    main()
