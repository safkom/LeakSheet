"""Dump all rows for a specific era to see sub-headers/sections."""
import sys
from src.parser import extract_table, detect_columns, ERA_STATS_PATTERN, _era_match_key

rows = extract_table(open('Trackers/Ye Tracker - Google Drive_files/sheet.html').read())
col_map = detect_columns(rows[0])
era_col = col_map.get('era', 0)
name_col = col_map.get('name', 1)

# Build era keys from era header rows
era_names = []
for i, row in enumerate(rows):
    texts = [c.text.strip() for c in row]
    first = texts[0] if texts else ''
    if ERA_STATS_PATTERN.search(first):
        second = texts[name_col] if name_col < len(texts) else ''
        if second:
            era_names.append((i, second))

# Show all eras
target = sys.argv[1] if len(sys.argv) > 1 else None
if target is None:
    print("Available eras:")
    for i, (row_idx, name) in enumerate(era_names):
        print(f"  {i}: {name}")
    sys.exit(0)

# Find target era
target_lower = target.lower()
target_era_idx = None
target_era_name = None
for i, (row_idx, name) in enumerate(era_names):
    if target_lower in name.lower():
        target_era_idx = row_idx
        target_era_name = name
        break

if target_era_idx is None:
    print(f"Era not found: {target}")
    sys.exit(1)

# Find next era header (to bound our range)
next_era_idx = len(rows)
for i, row in enumerate(rows):
    if i <= target_era_idx:
        continue
    texts = [c.text.strip() for c in row]
    first = texts[0] if texts else ''
    if ERA_STATS_PATTERN.search(first):
        next_era_idx = i
        break

print(f"=== Era: {target_era_name} (rows {target_era_idx} to {next_era_idx-1}) ===\n")

# Dump all rows in this era
for i in range(target_era_idx, min(next_era_idx, target_era_idx + 200)):
    row = rows[i]
    texts = [c.text.strip() for c in row]
    era_val = texts[era_col] if era_col < len(texts) else ''
    name_val = texts[name_col] if name_col < len(texts) else ''
    non_empty = [(j, t) for j, t in enumerate(texts) if t]
    
    # Classify this row
    if i == target_era_idx:
        label = "ERA_HEADER"
    elif not any(t for t in texts if t):
        label = "EMPTY"
    elif name_val and era_val:
        label = "SONG"
    elif era_val and not name_val:
        label = "SUB-HDR?"
    else:
        label = "OTHER"
    
    if label == "EMPTY":
        continue
        
    print(f"ROW {i} [{label}]")
    print(f"  era_col({era_col}): {era_val!r}")
    print(f"  name_col({name_col}): {name_val!r}")
    if non_empty:
        print(f"  non-empty({len(non_empty)}): {non_empty[:8]}")
    print()
