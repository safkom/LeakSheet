#!/usr/bin/env python3
"""Investigate more failing trackers — classify era stats patterns."""
import sys
sys.path.insert(0, "/Users/safko/Dev/LeakSheet")

from src.fetcher import fetch_sheet_html
from src.parser import extract_table, ERA_STATS_PATTERN
import re

# Only check trackers that FAILED (from first 64 results)
trackers = [
    ("PinkPantheress", "1Z_c3abjaM10CjGaJ5yjDqaEWB8YnDVuDaAJCp0EJBu8"),
    ("Sabrina Carpenter", "1XDdYqcxbozqNE-2Dh8HlQt4KsUiFLdo2NrAzelweFKs"),
    ("Selena Gomez", "10NdIn1iVdHxt0XbZmssh7pw7p7bsbFML6hwDIF4hMvU"),
    ("Steve Lacy", "1Ts7m74Qhnqy_50l2dLUWpAa0rVswvTuR9o1IJNEliSk"),
    ("Travis Scott", "1gJqbQrb3dIWF-PLMsKkNUrftpQb8zxsZFDAIpSvT5Fo"),
    ("Usher", "10b5EFPYc5Qhn3A7arsruyeVOYdU4Ab9TuQqELV9joa8"),
    ("Wu-Tang Clan", "1dA2h1kQffOmUUeCy6YMu8IYdGGqnhnWuabKdK7emyyU"),
    ("XXXTENTACION", "1wKq7lSERmXYutRFxipNbFFc-DUdqhVXWWlFnqkzwRFA"),
    ("Young Thug", "12zc2reK5y8XP6SQhv1ujQtiG9VpJy7yDWwDuE-S-wpc"),
    ("Yung Lean", "1bAAb6E7_r-9TWlHuKY_re-KZwU2yt_3tbWGTZcKu_Wc"),
    ("Yuno Miles", "1i0OISTGJvNe3vc6TKpO7vRtMJ2Re0y64eAwi1F5y26c"),
]

for name, sid in trackers:
    url = f"https://docs.google.com/spreadsheets/d/{sid}/htmlview"
    try:
        html, title = fetch_sheet_html(url, use_cache=True)
        rows = extract_table(html)
        print(f"\n{'='*60}")
        print(f"=== {name} === Rows: {len(rows)}")
        if rows:
            hdr = [c.text.strip().replace('\n', ' ')[:30] for c in rows[0]]
            print(f"Header: {hdr}")
            # Show first 12 non-empty rows
            shown = 0
            for i, row in enumerate(rows[1:min(25, len(rows))], 1):
                first = row[0].text.strip().replace('\n', ' | ')[:80] if row else ""
                second = row[1].text.strip().replace('\n', ' | ')[:60] if len(row) > 1 else ""
                if first or second:
                    # Check if this matches our pattern
                    match = ERA_STATS_PATTERN.search(row[0].text)
                    marker = " <<ERA>>" if match else ""
                    # Check for common digit-starting patterns
                    has_digits = bool(re.match(r'\d', first))
                    if has_digits:
                        marker += " [DIGITS]"
                    print(f"  R{i}: [{first[:60]}] | [{second[:50]}]{marker}")
                    shown += 1
                if shown >= 10:
                    break
    except Exception as e:
        print(f"\n{name}: ERROR: {type(e).__name__}: {str(e)[:100]}")
