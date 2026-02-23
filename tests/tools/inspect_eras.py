#!/usr/bin/env python3
"""Inspect detected eras and their song counts from parsed tracker data.

Usage:
    python -m tests.tools.inspect_eras [--tracker NAME] [--verbose]

Examples:
    python -m tests.tools.inspect_eras
    python -m tests.tools.inspect_eras --tracker "Kendrick"
    python -m tests.tools.inspect_eras --tracker "Carti" --verbose
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import discover_trackers, TRACKERS_DIR
from src.parser import parse_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect parsed eras from tracker data")
    parser.add_argument("--tracker", type=str, help="Artist name filter (substring match)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show era descriptions")
    args = parser.parse_args()

    trackers = discover_trackers(TRACKERS_DIR)
    if not trackers:
        print("No trackers found in", TRACKERS_DIR)
        return

    for artist_name, sheet_path in trackers:
        if args.tracker and args.tracker.lower() not in artist_name.lower():
            continue

        artist = parse_file(sheet_path, artist_name)

        print(f"\n{'='*80}")
        print(f"ARTIST: {artist.name} (slug: {artist.slug})")
        print(f"TOTAL ERAS: {len(artist.eras)}")
        print(f"TOTAL SONGS: {artist.total_songs}")
        print(f"TOTAL VERSIONS: {artist.total_versions}")
        print(f"{'='*80}")

        for i, era in enumerate(artist.eras):
            badge_counts = {}
            for song in era.songs:
                for v in song.versions:
                    if v.badge:
                        badge_counts[v.badge.value] = badge_counts.get(v.badge.value, 0) + 1

            badge_str = ""
            if badge_counts:
                parts = [f"{v}x {k}" for k, v in sorted(badge_counts.items())]
                badge_str = f"  [{', '.join(parts)}]"

            print(f"\n  Era {i+1}: {era.name}")
            print(f"    Songs: {era.song_count} ({era.version_count} versions){badge_str}")
            if era.stats_raw:
                print(f"    Stats: {era.stats_raw[:80]}{'...' if len(era.stats_raw or '') > 80 else ''}")

            if args.verbose and era.description:
                desc = era.description[:200] + "..." if len(era.description) > 200 else era.description
                print(f"    Desc:  {desc}")


if __name__ == "__main__":
    main()
