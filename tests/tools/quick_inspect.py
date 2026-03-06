#!/usr/bin/env python3
"""Quick inspection of parser output for known trackers."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.fetcher import fetch_and_parse

urls = [
    ("Ye", "https://yetracker.net/"),
    ("Baby Keem", "https://docs.google.com/spreadsheets/d/1-FxUYaxBqav0G6txAAixy7bhTGs86sItN_0_F8ekeKQ/htmlview"),
    ("Kendrick Lamar", "https://docs.google.com/spreadsheets/d/1ogXipStHPpqEMgCDvxpWXQ7Yzly3YZx6riP25ChoxNM/htmlview"),
    ("Playboi Carti", "https://docs.google.com/spreadsheets/d/1ivoRJskby8zykhH_szifY4a1HIQCTnVh6c2WfIfMbkM/htmlview"),
    ("A$AP Rocky", "https://docs.google.com/spreadsheets/d/1rbt_VyQyHEfVRv_XmVBNrwMyF0uMx7FF-1T8-N0wf0E/"),
    ("Eminem", "https://docs.google.com/spreadsheets/d/1x9tTOOqH5WpKOoptdQzABSN_x8oZbMgzIGlGH9w1IKA/edit?pli=1&gid=1792554832#gid=1792554832"),
    ("Frank Ocean", "https://docs.google.com/spreadsheets/u/1/d/1SHQW94xZfgCyupSPdhiKh4UwMkl_ibgmzvcD0Gxwvcw/edit?gid=1203501126#gid=1203501126"),
    ("Lil Uzi Vert", "https://docs.google.com/spreadsheets/d/1GArvzS4dyr519XDRK2sIVrY0RUL9zLlnt8il-Vj7ThY/edit#gid=0"),
]

for name, url in urls:
    try:
        artist = fetch_and_parse(url, artist_name=name, cache_ttl=86400)
        meta = artist.parse_metadata
        print(f"=== {name} ===")
        print(f"  Eras: {len(artist.eras)}, Songs: {artist.total_songs}, Versions: {artist.total_versions}")
        print(f"  Skipped: {meta.skipped_rows}/{meta.total_rows} ({meta.skipped_rows/meta.total_rows*100:.1f}%)" if meta.total_rows > 0 else "  No rows")
        if meta.unmatched_rows:
            print(f"  Unmatched rows: {meta.unmatched_rows[:3]}")
        for era in artist.eras:
            sections_info = ""
            named_sections = [s.name for s in era.sections if s.name]
            if named_sections:
                sections_info = f" sections={named_sections}"
            zero_mark = " *** ZERO SONGS ***" if era.song_count == 0 else ""
            print(f"    Era: {era.name!r} -> {era.song_count} songs{sections_info}{zero_mark}")
        print()
    except Exception as e:
        print(f"=== {name} === ERROR: {type(e).__name__}: {e}")
        print()
