"""Quick check of Baby Keem and Carti tracker structures."""

import re
from src.fetcher import fetch_sheet_html
from src.parser import extract_table, _is_era_header

def check_tracker(url, name):
    html, title = fetch_sheet_html(url)
    rows = extract_table(html)
    era_count = sum(1 for r in rows if _is_era_header(r))
    img_count = len(re.findall(r'<img', html, re.I))
    print(f"{name}: {len(rows)} rows, {era_count} eras, {img_count} imgs")

    for i, row in enumerate(rows):
        for cell in row:
            if "Total Links" in cell.text or "Total Full" in cell.text:
                print(f"  Global stats at row {i}:")
                for j, c in enumerate(row):
                    if c.text.strip():
                        print(f"    col[{j}]: \"{c.text[:140]}\"")
                break

    # First era header
    for i, row in enumerate(rows[:100]):
        if _is_era_header(row):
            print(f"  First era header at row {i}:")
            for j, c in enumerate(row):
                if c.text.strip():
                    print(f"    col[{j}]: \"{c.text[:100]}\"")
            break

    print()

check_tracker(
    "https://docs.google.com/spreadsheets/d/1-FxUYaxBqav0G6txAAixy7bhTGs86sItN_0_F8ekeKQ/htmlview",
    "Baby Keem"
)
check_tracker(
    "https://docs.google.com/spreadsheets/d/1ivoRJskby8zykhH_szifY4a1HIQCTnVh6c2WfIfMbkM/htmlview",
    "Playboi Carti"
)
