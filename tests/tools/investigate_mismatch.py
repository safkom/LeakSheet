"""Investigate era version count mismatches between stats and parsed data."""

import sys
sys.path.insert(0, ".")

from src.fetcher import fetch_sheet_html
from src.parser import extract_table, detect_columns, _is_era_header, _era_match_key, _is_section_separator, _is_empty_row, _get_cell_text
from src.models import parse_era_stats


def investigate_era(url, target_era_substring):
    """Show all rows belonging to a specific era, highlighting potential misses."""
    html, title = fetch_sheet_html(url)
    rows = extract_table(html)
    col_map = detect_columns(rows[0])

    # Find the target era header
    target_row_idx = None
    next_era_idx = None
    era_name = None

    for i, row in enumerate(rows):
        if _is_era_header(row):
            name = _get_cell_text(row, col_map.get("name", 1))
            if target_era_substring.lower() in name.lower():
                target_row_idx = i
                era_name = name
                stats_raw = _get_cell_text(row, 0)
                stats = parse_era_stats(stats_raw) if stats_raw else None
                print(f"Found era at row {i}: {name}")
                print(f"  Stats raw: {stats_raw[:100]}")
                if stats:
                    print(f"  Stats parsed: og={stats.og_files} full={stats.full} tagged={stats.tagged} partial={stats.partial} snips={stats.snippets} stem={stats.stem_bounces} unavail={stats.unavailable} → total={stats.total}")
            elif target_row_idx is not None and next_era_idx is None:
                next_era_idx = i
                print(f"Next era at row {i}: {name}")
                break

    if target_row_idx is None:
        print(f"Era containing '{target_era_substring}' not found!")
        return

    if next_era_idx is None:
        next_era_idx = len(rows)

    # Walk through all rows in the era and classify them
    era_col = col_map.get("era", 0)
    name_col = col_map.get("name", 1)
    era_key = _era_match_key(era_name)

    song_count = 0
    skipped_rows = []

    for i in range(target_row_idx + 1, next_era_idx):
        row = rows[i]

        if _is_empty_row(row):
            continue

        if _is_section_separator(row):
            continue

        if _is_era_header(row):
            # This shouldn't happen (we break at next era)
            break

        row_era = _get_cell_text(row, era_col)
        song_name = _get_cell_text(row, name_col)

        if song_name:
            song_count += 1
        else:
            # Row has no song name — this is what we're missing
            texts = [c.text[:40] for c in row if c.text.strip()]
            skipped_rows.append((i, row_era, song_name, texts))

    print(f"\n  Rows with song names in range [{target_row_idx+1}..{next_era_idx}]: {song_count}")
    if skipped_rows:
        print(f"  Rows without song names (potential misses):")
        for idx, era, name, texts in skipped_rows:
            print(f"    row[{idx}]: era='{era[:30]}' name='{name}' texts={texts}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://yetracker.net/"
    era = sys.argv[2] if len(sys.argv) > 2 else "Graduation"
    investigate_era(url, era)
