#!/usr/bin/env python3
"""Inspect key trackers to gather baseline parser output for ground truth."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.fetcher import async_fetch_and_parse

TRACKERS = [
    ("Ye", "https://docs.google.com/spreadsheets/d/1vW-nFbnR02F9BEnNhwwb6bGcEMvYTBIa3LBjfRSDNig/htmlview"),
    ("Baby Keem", "https://docs.google.com/spreadsheets/d/14Z6sAmVVuz2GhR5O0hNixd5f74v5zPFVWlo4_u7FJM0/htmlview"),
    ("Kendrick Lamar", "https://docs.google.com/spreadsheets/d/1u-TA7oYeJOMkAFNnCDfq-D0JxY2-x1W_WBBS1Ax2XCw/htmlview"),
    ("Playboi Carti", "https://docs.google.com/spreadsheets/d/1MmjtxmHCFI4CAxcCCMUEB2PNA_QfWc14JmmxDPFPd5I/htmlview"),
    ("Lil Uzi Vert", "https://docs.google.com/spreadsheets/d/1cFkNcHmiCHWG3MJ14t_SMWMPWRA3p0m8GqNXr2xAKYw/htmlview"),
    ("Doja Cat", "https://docs.google.com/spreadsheets/d/1_NwxP5mGGEj7stY0Dr_hI_Pb4m8LBIyt3Cb-OoTJPtc/htmlview"),
    ("ASAP Rocky", "https://docs.google.com/spreadsheets/d/16POwKm7MZMkFq5mUhDdBG3UgodJc3Z1qN3jqHPVAjpE/htmlview"),
    ("Eminem", "https://docs.google.com/spreadsheets/d/1G7J4mJoMN0oJG7HDm33mmjJR-ypmmHXMPp_yqvOQKhI/htmlview"),
    ("Chief Keef", "https://docs.google.com/spreadsheets/d/1mVhZdaUeqLIVJLkmB2c2OKYBhMKkRUhWyxG3UKE_Ax8/htmlview"),
    ("Don Toliver", "https://docs.google.com/spreadsheets/d/1IfJpKfV3oxQCIhT1QKt9nQy3Wo6k48bKUF8JxBxZ4ts/htmlview"),
    ("Denzel Curry", "https://docs.google.com/spreadsheets/d/1VcBDCXjJBnOl_zPhY964fmCFGmIh8Wg4IvjjHYJb5is/htmlview"),
]


async def inspect(name, url):
    try:
        artist = await async_fetch_and_parse(
            url, artist_name=name, use_cache=True, cache_ttl=86400
        )
        zero_eras = []
        section_eras = []
        era_details = []
        for e in artist.eras:
            sections = [s.name for s in e.sections if s.name]
            sc = e.song_count
            if sc == 0:
                zero_eras.append(e.name)
            if sections:
                section_eras.append({"era": e.name, "sections": sections})
            era_details.append({"name": e.name, "songs": sc})

        meta = artist.parse_metadata
        um = meta.unmatched_rows[:10] if meta else []
        return {
            "name": name,
            "eras": len(artist.eras),
            "songs": artist.total_songs,
            "versions": artist.total_versions,
            "skip_pct": round(
                meta.skipped_rows / meta.total_rows * 100, 1
            )
            if meta and meta.total_rows
            else 0,
            "zero_song_eras": zero_eras,
            "sections": section_eras,
            "unmatched": um,
            "fuzzy": meta.fuzzy_matched_rows if meta else 0,
            "era_details": era_details,
        }
    except Exception as e:
        return {"name": name, "error": str(e)}


async def main():
    results = await asyncio.gather(*[inspect(n, u) for n, u in TRACKERS])
    for r in results:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        print("---")


if __name__ == "__main__":
    asyncio.run(main())
