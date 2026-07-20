"""Deep investigation of rows in a specific era range."""

import sys
sys.path.insert(0, ".")

from src.fetcher import fetch_sheet_html
from src.parser import extract_table, detect_columns, _is_era_header, _get_cell_text, _is_empty_row
from src.models import parse_era_stats


def deep_investigate(url, target_era_substring):
    html, title = fetch_sheet_html(url)
    rows = extract_table(html)
    col_map = detect_columns(rows[0])

    # Find era boundaries
    target_row_idx = None
    next_era_idx = None
    era_name = None

    for i, row in enumerate(rows):
        if _is_era_header(row):
            name = _get_cell_text(row, col_map.get("name", 1))
            if target_row_idx is not None and next_era_idx is None:
                next_era_idx = i
                break
            if target_era_substring.lower() in name.lower():
                target_row_idx = i
                era_name = name

    if target_row_idx is None:
        print(f"Era not found!")
        return

    if next_era_idx is None:
        next_era_idx = min(target_row_idx + 200, len(rows))

    print(f"Era '{era_name}' rows {target_row_idx+1} to {next_era_idx-1}")
    print(f"Col map: {col_map}")

    era_col = col_map.get("era", 0)
    name_col = col_map.get("name", 1)
    notes_col = col_map.get("notes", 2)
    avail_col = col_map.get("available_length", -1)

    total_non_empty = 0
    has_name = 0
    no_name_but_data = 0

    for i in range(target_row_idx + 1, next_era_idx):
        row = rows[i]
        if _is_empty_row(row):
            continue

        total_non_empty += 1
        row_era = _get_cell_text(row, era_col)
        song_name = _get_cell_text(row, name_col)
        notes = _get_cell_text(row, notes_col)
        avail = _get_cell_text(row, avail_col) if avail_col >= 0 else ""

        if song_name:
            has_name += 1
        else:
            no_name_but_data += 1
            # Show this row
            all_texts = [(j, c.text[:50]) for j, c in enumerate(row) if c.text.strip()]
            print(f"  ROW {i} (no name): era='{row_era[:30]}' all_cells={all_texts}")

    print(f"\nTotal non-empty rows: {total_non_empty}")
    print(f"  With name: {has_name}")
    print(f"  No name but data: {no_name_but_data}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://yetracker.net/"
    era = sys.argv[2] if len(sys.argv) > 2 else "Graduation"
    deep_investigate(url, era)
