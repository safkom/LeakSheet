#!/usr/bin/env python3
"""Investigate failing trackers — dump era stats patterns from first cells."""
import sys
sys.path.insert(0, "/Users/safko/Dev/LeakSheet")

from src.fetcher import fetch_sheet_html
from src.parser import extract_table, ERA_STATS_PATTERN

# Trackers that fail with 0 eras
trackers = [
    ("Billie Eilish", "1xwS_bEbYRSy1aVs0qE92BMMlXjAipP1pDekP5VPHz-g"),
    ("Doja Cat", "1_NwxP5mGGEj7stY0Dr_hI_Pb4m8LBIyt3Cb-OoTJPtc"),
    ("Gucci Mane", "1F-0vYFU1_F3IdZTAN5-H0YWvzhW88vg95AmVxZxoCEM"),
    ("J. Cole", "1hjMtB-acUEpXYkR6TWQVeVoUzSLrAVIdy1lMoM6aFFw"),
    ("Joji / Pink Guy", "1FPlWbXnx94y5FODJ2qniLf0BzViNSAmj6Xdfw1ZNwQ4"),
    ("JPEGMAFIA", "1IhfNqEOtwczA6JH52gv2feerMqlJEbaDV4bxaIr7gkI"),
    ("Kali Uchis", "1232zeg65iIVLI-wIsMyE7vatZBKY0i0YOCpk0Ml7jxM"),
    ("Kid Cudi", "1fj9HcbyLbu5NGwJzbl1lExQud3FNKv-JUU6NY4OKM9Y"),
    ("Chief Keef", "1oDE9gTnEG7ufPQIOMjLTegfI47qtgNCxngmxxHZL4qA"),
    ("Childish Gambino", "1eyBjj7qPxIT_P93RaSPZf5hTJemGi5jMqSJF777OsdE"),
]

for name, sid in trackers:
    url = f"https://docs.google.com/spreadsheets/d/{sid}/htmlview"
    try:
        html, title = fetch_sheet_html(url, use_cache=True)
        rows = extract_table(html)
        print(f"\n{'='*80}")
        print(f"=== {name} === Rows: {len(rows)}")
        if rows:
            print(f"Header cols: {[c.text.strip()[:30] for c in rows[0]]}")
            # Find rows where first cell has digits (potential era headers)
            found_era = False
            for i, row in enumerate(rows[1:min(30, len(rows))], 1):
                first = row[0].text.strip().replace('\n', ' | ')[:120]
                if first and any(c.isdigit() for c in first[:5]):
                    match = ERA_STATS_PATTERN.search(row[0].text)
                    era_name = row[1].text.strip()[:60] if len(row) > 1 else ""
                    marker = "MATCH" if match else "NO_MATCH"
                    print(f"  Row {i} [{marker}]: {first}")
                    if era_name:
                        print(f"    Era name: {era_name}")
                    found_era = True
            if not found_era:
                # Show first 5 non-empty rows
                print("  No digit-starting rows found. First rows:")
                shown = 0
                for i, row in enumerate(rows[1:], 1):
                    texts = [c.text.strip()[:40] for c in row[:4] if c.text.strip()]
                    if texts:
                        print(f"  Row {i}: {texts}")
                        shown += 1
                    if shown >= 8:
                        break
    except Exception as e:
        print(f"\n{name}: ERROR: {e}")
