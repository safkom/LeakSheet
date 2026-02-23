#!/usr/bin/env python3
"""Inspect parsed songs for a specific artist/era.

Usage:
    python -m tests.tools.inspect_songs --tracker NAME [--era ERA] [--limit N] [--badges-only]

Examples:
    python -m tests.tools.inspect_songs --tracker "Baby Keem"
    python -m tests.tools.inspect_songs --tracker "Ye" --era "Before The College Dropout"
    python -m tests.tools.inspect_songs --tracker "Kendrick" --badges-only
    python -m tests.tools.inspect_songs --tracker "Carti" --limit 20
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import discover_trackers, TRACKERS_DIR
from src.parser import parse_file
from src.models import Badge


BADGE_EMOJI = {
    Badge.BEST: "⭐",
    Badge.SPECIAL: "✨",
    Badge.WORST: "🗑️",
    Badge.GRAIL: "🏆",
    Badge.WANTED: "🏅",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect parsed songs from tracker data")
    parser.add_argument("--tracker", type=str, required=True, help="Artist name filter (substring match)")
    parser.add_argument("--era", type=str, help="Era name filter (substring match)")
    parser.add_argument("--limit", type=int, default=0, help="Max songs to show per era (0 = all)")
    parser.add_argument("--badges-only", action="store_true", help="Only show songs with badges")
    parser.add_argument("--with-links", action="store_true", help="Show download links")
    parser.add_argument("--search", type=str, help="Search song names (substring match)")
    args = parser.parse_args()

    trackers = discover_trackers(TRACKERS_DIR)
    matched = None

    for artist_name, sheet_path in trackers:
        if args.tracker.lower() in artist_name.lower():
            matched = (artist_name, sheet_path)
            break

    if not matched:
        print(f"No tracker found matching '{args.tracker}'")
        print("Available:", [name for name, _ in trackers])
        return

    artist_name, sheet_path = matched
    artist = parse_file(sheet_path, artist_name)

    print(f"\nARTIST: {artist.name}")
    print(f"{'='*80}")

    for era in artist.eras:
        if args.era and args.era.lower() not in era.name.lower():
            continue

        songs_shown = 0
        era_header_printed = False

        for song in era.songs:
            for version in song.versions:
                # Apply filters
                if args.badges_only and version.badge is None:
                    continue
                if args.search and args.search.lower() not in version.name.lower():
                    continue
                if args.limit and songs_shown >= args.limit:
                    break

                if not era_header_printed:
                    print(f"\n  ERA: {era.name} ({era.song_count} songs, {era.version_count} versions)")
                    print(f"  {'-'*70}")
                    era_header_printed = True

                badge = BADGE_EMOJI.get(version.badge, " ") if version.badge else " "

                print(f"    {badge} {version.name}")

                details = []
                if version.track_length:
                    details.append(f"Length: {version.track_length}")
                if version.available_length:
                    details.append(f"Avail: {version.available_length}")
                if version.quality:
                    details.append(f"Quality: {version.quality}")
                if version.leak_date:
                    details.append(f"Leaked: {version.leak_date}")
                if version.file_date:
                    details.append(f"File: {version.file_date}")
                if version.type:
                    details.append(f"Type: {version.type}")
                if version.date_of_recording:
                    details.append(f"Recorded: {version.date_of_recording}")

                if details:
                    print(f"      {' | '.join(details)}")

                if args.with_links and version.links:
                    for link in version.links:
                        print(f"      🔗 {link}")

                songs_shown += 1

            if args.limit and songs_shown >= args.limit:
                remaining = era.version_count - songs_shown
                if remaining > 0:
                    print(f"    ... ({remaining} more versions)")
                break


if __name__ == "__main__":
    main()
