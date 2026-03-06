"""Check what sub-era sections exist in the Ye tracker."""
from src.parser import extract_table, detect_columns, ERA_STATS_PATTERN

rows = extract_table(open('Trackers/Ye Tracker - Google Drive_files/sheet.html').read())
col_map = detect_columns(rows[0])
era_col = col_map.get('era', 0)
name_col = col_map.get('name', 1)

# Collect known era keys
era_keys = set()
for row in rows:
    texts = [c.text.strip() for c in row]
    first = texts[0] if texts else ''
    if ERA_STATS_PATTERN.search(first):
        second = texts[name_col] if name_col < len(texts) else ''
        if second:
            era_keys.add(second.split('(')[0].strip().lower())

# Now find rows that look like sub-headers: era column has text that's NOT a known era key
# and name column is empty or the row has very few non-empty cells
current_era = None
for i, row in enumerate(rows):
    texts = [c.text.strip() for c in row]
    first = texts[0] if texts else ''
    
    if ERA_STATS_PATTERN.search(first):
        second = texts[name_col] if name_col < len(texts) else ''
        current_era = second.split('(')[0].strip()
        continue
    
    if not current_era:
        continue

    era_val = texts[era_col] if era_col < len(texts) else ''
    name_val = texts[name_col] if name_col < len(texts) else ''
    
    # Sub-header pattern: era_col has text, name_col is empty, few non-empty cells
    if era_val and not name_val:
        non_empty = [t for t in texts if t]
        if len(non_empty) <= 3:
            print(f"ROW {i} | Era: {current_era} | Sub-header: '{era_val}'")
