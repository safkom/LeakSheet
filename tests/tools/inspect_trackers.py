#!/usr/bin/env python3
"""Inspect specific trackers for era/section structure to build ground truth."""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.fetcher import fetch_and_parse

trackers = [
    ("Lil Uzi Vert", "https://docs.google.com/spreadsheets/d/1zqqdIds1iwnx4lh29iF1IlraeuqfGhxH9qLNlWOnryo/edit?gid=1160569231#gid=1160569231"),
    ("A$AP Rocky", "https://docs.google.com/spreadsheets/d/1rbt_VyQyHEfVRv_XmVBNrwMyF0uMx7FF-1T8-N0wf0E/"),
    ("Eminem", "https://docs.google.com/spreadsheets/d/1x9tTOOqH5WpKOoptdQzABSN_x8oZbMgzIGlGH9w1IKA/edit?pli=1&gid=1792554832#gid=1792554832"),
    ("Doja Cat", "https://docs.google.com/spreadsheets/d/1_NwxP5mGGEj7stY0Dr_hI_Pb4m8LBIyt3Cb-OoTJPtc/edit"),
    ("Denzel Curry", "https://docs.google.com/spreadsheets/d/1Pyi72FNT6KWuQE3g4BmIDCV26HMfKFcE650Duyia43o/edit?gid=788157788#gid=788157788"),
    ("Chief Keef", "https://docs.google.com/spreadsheets/d/1oDE9gTnEG7ufPQIOMjLTegfI47qtgNCxngmxxHZL4qA/edit#gid=1792554832"),
    ("Don Toliver", "https://docs.google.com/spreadsheets/d/1qsO4SuzzB17d5orqbKWHsaQsRdk0lzTSF9rV2FwQf-Q/edit?gid%3D1535277716%23gid%3D1535277716"),
]

for name, url in trackers:
    try:
        artist = fetch_and_parse(url, artist_name=name, cache_ttl=86400)
        meta = artist.parse_metadata
        print(f"=== {name} ===")
        print(f"  Eras: {len(artist.eras)}, Songs: {artist.total_songs}, Versions: {artist.total_versions}")
        if meta and meta.total_rows > 0:
            print(f"  Skipped: {meta.skipped_rows}/{meta.total_rows} ({meta.skipped_rows/meta.total_rows*100:.1f}%)")
        if meta and meta.unmatched_rows:
            print(f"  Unmatched ({len(meta.unmatched_rows)}): {meta.unmatched_rows[:5]}")
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
