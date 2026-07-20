#!/usr/bin/env python3
"""Debug zero-song eras by examining raw row data around them."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.parser import extract_table, _era_match_key, ERA_STATS_PATTERN
from src.config import discover_trackers, TRACKERS_DIR


def main():
    trackers = discover_trackers(TRACKERS_DIR)
    
    for artist_name, sheet_path in trackers:
        html = sheet_path.read_text(encoding="utf-8")
        rows = extract_table(html)
        
        # Find all era headers and collect their match keys
        era_keys = {}  # match_key -> (row_idx, full_name)
        era_order = []
        
        for i, row in enumerate(rows):
            if not row:
                continue
            first_cell = row[0].text.strip()
            if ERA_STATS_PATTERN.search(first_cell):
                name_cell = row[1].text.strip() if len(row) > 1 else ""
                key = _era_match_key(name_cell)
                era_keys[key] = (i, name_cell)
                era_order.append((i, key, name_cell))
        
        # Now check which era keys actually appear in song rows
        song_era_values = set()
        for i, row in enumerate(rows):
            if not row or i == 0:
                continue
            first_cell = row[0].text.strip()
            if first_cell and not ERA_STATS_PATTERN.search(first_cell):
                song_era_values.add(first_cell)
        
        # Find mismatches
        unmatched = []
        for idx, key, full_name in era_order:
            if key not in song_era_values:
                # Check if there's a close match
                close = [v for v in song_era_values if key in v or v in key]
                unmatched.append((idx, key, full_name, close))
        
        if unmatched:
            print(f"\n{'='*60}")
            print(f"ARTIST: {artist_name}")
            print(f"{'='*60}")
            for idx, key, full_name, close in unmatched:
                print(f"  Row {idx}: Era key={key!r}")
                print(f"    Full name: {full_name!r}")
                if close:
                    print(f"    Close matches in song rows: {close}")
                else:
                    print(f"    NO matches found in any song row")
                    # Look at the rows right after this era header
                    print(f"    Next 5 rows:")
                    for j in range(idx+1, min(idx+6, len(rows))):
                        row = rows[j]
                        c0 = row[0].text[:50] if row else ""
                        c1 = row[1].text[:50] if len(row) > 1 else ""
                        print(f"      Row {j}: col0={c0!r}  col1={c1!r}")


if __name__ == "__main__":
    main()
