#!/usr/bin/env python3
"""Dump raw table rows from any tracker HTML file.

Usage:
    python -m tests.tools.dump_raw_table [--tracker NAME] [--rows N] [--cols N]

Examples:
    python -m tests.tools.dump_raw_table
    python -m tests.tools.dump_raw_table --tracker "Baby Keem" --rows 20
    python -m tests.tools.dump_raw_table --tracker "Ye" --rows 10 --cols 5
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import discover_trackers, TRACKERS_DIR
from src.parser import extract_table


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump raw table rows from tracker HTML")
    parser.add_argument("--tracker", type=str, help="Artist name filter (substring match)")
    parser.add_argument("--rows", type=int, default=50, help="Max rows to display (default: 50)")
    parser.add_argument("--cols", type=int, default=12, help="Max columns to display (default: 12)")
    parser.add_argument("--start", type=int, default=0, help="Starting row index (default: 0)")
    parser.add_argument("--show-classes", action="store_true", help="Show CSS classes for each cell")
    parser.add_argument("--show-links", action="store_true", help="Show extracted links for each cell")
    args = parser.parse_args()

    trackers = discover_trackers(TRACKERS_DIR)
    if not trackers:
        print("No trackers found in", TRACKERS_DIR)
        return

    for artist_name, sheet_path in trackers:
        if args.tracker and args.tracker.lower() not in artist_name.lower():
            continue

        html = sheet_path.read_text(encoding="utf-8")
        rows = extract_table(html)

        print(f"\n{'='*80}")
        print(f"TRACKER: {artist_name}")
        print(f"FILE:    {sheet_path}")
        print(f"TOTAL ROWS: {len(rows)}")
        print(f"{'='*80}")

        end = min(args.start + args.rows, len(rows))
        for i in range(args.start, end):
            row = rows[i]
            # Skip fully empty rows unless they're in the first few
            if i > 1 and all(not c.text.strip() for c in row):
                continue

            cells_display = []
            for j, cell in enumerate(row[:args.cols]):
                text = cell.text[:60] + "..." if len(cell.text) > 60 else cell.text
                if args.show_links and cell.links:
                    text += f" [+{len(cell.links)} links]"
                if args.show_classes and cell.css_class:
                    text += f" <{cell.css_class}>"
                cells_display.append(text)

            print(f"Row {i:4d}: {cells_display}")

        if end < len(rows):
            print(f"  ... ({len(rows) - end} more rows)")


if __name__ == "__main__":
    main()
