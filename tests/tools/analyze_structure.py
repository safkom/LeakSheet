"""Analyze HTML structure of live trackers for era stats, global stats, and images."""

import re
import sys
from src.fetcher import fetch_sheet_html
from src.parser import extract_table, _is_era_header

def analyze_tracker(url):
    print(f"Fetching: {url}")
    html, title = fetch_sheet_html(url)
    print(f"Title: {title}")
    print(f"HTML length: {len(html):,}")

    rows = extract_table(html)
    print(f"Total rows: {len(rows)}")

    # 1. Find img tags in the raw HTML near era headers
    era_names = []
    for i, row in enumerate(rows):
        if _is_era_header(row):
            name = row[1].text if len(row) > 1 else "?"
            era_names.append((i, name))

    print(f"\nFound {len(era_names)} era headers")

    # Check for img tags in raw HTML
    img_pattern = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
    all_imgs = img_pattern.findall(html)
    print(f"Total <img> tags in HTML: {len(all_imgs)}")
    if all_imgs:
        print(f"  First img: {all_imgs[0][:150]}")

    # 2. Look at the last 50 rows for global stats
    print("\n--- LAST 20 ROWS ---")
    for i, row in enumerate(rows[-20:], start=len(rows)-20):
        texts = [c.text[:60] for c in row if c.text.strip()]
        if texts:
            print(f"  row[{i}]: {texts}")

    # 3. Examine first 2 era headers in detail
    print("\n--- FIRST 2 ERA HEADERS (detail) ---")
    for idx, name in era_names[:2]:
        row = rows[idx]
        print(f"\nEra at row {idx}: {name}")
        for j, cell in enumerate(row):
            txt = cell.text[:150] if cell.text else ''
            print(f"  col[{j}]: class=\"{cell.css_class}\" text=\"{txt}\" links={len(cell.links)}")

    # 4. Check for img in the raw HTML around each era
    # Find img src URLs near first era
    first_era_name = era_names[0][1] if era_names else None
    if first_era_name:
        idx = html.find(first_era_name[:30])
        if idx > -1:
            snippet = html[max(0, idx-3000):idx+1000]
            imgs_near = img_pattern.findall(snippet)
            print(f"\nImages near first era '{first_era_name[:40]}':")
            for img in imgs_near:
                print(f"  {img[:200]}")

    # 5. Find the global stats section - look for "Total Full" or "Total Links"
    print("\n--- GLOBAL STATS SEARCH ---")
    for i, row in enumerate(rows):
        for cell in row:
            if "Total Links" in cell.text or "Total Full" in cell.text:
                print(f"  Found global stats at row {i}:")
                for j, c in enumerate(row):
                    if c.text.strip():
                        print(f"    col[{j}]: \"{c.text[:200]}\"")
                break

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://yetracker.net/"
    analyze_tracker(url)
