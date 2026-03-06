#!/usr/bin/env python3
"""Investigate failing trackers — dump first rows to understand structure."""
import sys
sys.path.insert(0, ".")

from src.fetcher import fetch_sheet_html
from src.parser import extract_table

trackers = [
    ("Billie Eilish", "1xwS_bEbYRSy1aVs0qE92BMMlXjAipP1pDekP5VPHz-g"),
    ("Charli XCX", "1klHB69Kd9T22WhzhydwhhLelFth6r55D7KcpiLARePo"),
    ("Chief Keef", "1oDE9gTnEG7ufPQIOMjLTegfI47qtgNCxngmxxHZL4qA"),
    ("Childish Gambino", "1eyBjj7qPxIT_P93RaSPZf5hTJemGi5jMqSJF777OsdE"),
    ("Denzel Curry", "1Pyi72FNT6KWuQE3g4BmIDCV26HMfKFcE650Duyia43o"),
    ("Doja Cat", "1_NwxP5mGGEj7stY0Dr_hI_Pb4m8LBIyt3Cb-OoTJPtc"),
    ("Drake", "1v55XAPLzw1iuWxH1OQKajCIYPhW2BXcLoV4mXDZ55DI"),
    ("Frank Ocean", "1SHQW94xZfgCyupSPdhiKh4UwMkl_ibgmzvcD0Gxwvcw"),
]

for name, sid in trackers:
    url = f"https://docs.google.com/spreadsheets/d/{sid}/htmlview"
    try:
        html, title = fetch_sheet_html(url, use_cache=True)
        rows = extract_table(html)
        print(f"\n{'='*80}")
        print(f"=== {name} === Title: {title} | Rows: {len(rows)}")
        if rows:
            print(f"Header: {[c.text[:40] for c in rows[0]]}")
            for i, row in enumerate(rows[1:10], 1):
                first = row[0].text.strip()[:80] if row else ""
                second = row[1].text.strip()[:60] if len(row) > 1 else ""
                third = row[2].text.strip()[:60] if len(row) > 2 else ""
                if first or second:
                    print(f"  Row {i}: [{first}] | [{second}] | [{third}]")
    except Exception as e:
        print(f"\n{name}: ERROR: {e}")
