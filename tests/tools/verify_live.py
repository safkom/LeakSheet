"""Verify parsing accuracy against live tracker data.

Checks:
1. Era stats metadata matches parsed song counts
2. Global tracker stats are correctly parsed
3. Era art URLs are extracted
"""

import sys
sys.path.insert(0, ".")

from src.fetcher import fetch_and_parse
from src.models import EraStats


def verify_tracker(url, name):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"  {url}")
    print(f"{'='*70}")

    artist = fetch_and_parse(url)
    print(f"Artist: {artist.name} ({artist.slug})")
    print(f"Eras: {len(artist.eras)}, Songs: {artist.total_songs}, Versions: {artist.total_versions}")

    # Check era stats
    print(f"\n--- ERA STATS VERIFICATION ---")
    stats_match = 0
    stats_mismatch = 0
    eras_with_art = 0
    for era in artist.eras:
        has_art = "✅" if era.art_url else "❌"
        if era.art_url:
            eras_with_art += 1

        if era.stats:
            expected_total = era.stats.total
            actual_versions = era.version_count
            match_icon = "✅" if expected_total == actual_versions else "⚠️"
            if expected_total == actual_versions:
                stats_match += 1
            else:
                stats_mismatch += 1
                print(f"  {match_icon} {era.name[:50]:50s} | expected={expected_total:4d} actual_versions={actual_versions:4d} (diff={actual_versions - expected_total:+d}) art={has_art}")
        else:
            print(f"  ❓ {era.name[:50]:50s} | NO STATS                                    art={has_art}")

    print(f"\n  Summary: {stats_match} match, {stats_mismatch} mismatch, {eras_with_art}/{len(artist.eras)} eras with art")

    # Check global stats
    print(f"\n--- GLOBAL TRACKER STATS ---")
    if artist.tracker_stats:
        ts = artist.tracker_stats
        print(f"  Links:   total={ts.total_links}, missing={ts.missing_links}, needed={ts.sources_needed}, n/a={ts.not_available_links}")
        print(f"  Quality: lossless={ts.lossless}, cd={ts.cd_quality}, high={ts.high_quality}, low={ts.low_quality}, rec={ts.recordings}, n/a={ts.not_available_quality}")
        print(f"  Avail:   total_full={ts.total_full}, og={ts.og_files}, stem={ts.stem_bounces}, full={ts.full}, tagged={ts.tagged}, partial={ts.partial}, snips={ts.snippets}, unavail={ts.unavailable}")
        print(f"  Badges:  best={ts.best_of}, special={ts.special}, grails={ts.grails}, wanted={ts.wanted}, worst={ts.worst_of}")

        # Cross-check: sum of era stats vs global stats
        era_total_og = sum(e.stats.og_files for e in artist.eras if e.stats)
        era_total_full = sum(e.stats.full for e in artist.eras if e.stats)
        era_total_unavail = sum(e.stats.unavailable for e in artist.eras if e.stats)
        print(f"\n  Cross-check (sum of era stats):")
        print(f"    OG Files: era_sum={era_total_og} vs global={ts.og_files}")
        print(f"    Full:     era_sum={era_total_full} vs global={ts.full}")
        print(f"    Unavail:  era_sum={era_total_unavail} vs global={ts.unavailable}")
    else:
        print("  ❌ No global stats found!")

    # Show a few example art URLs
    print(f"\n--- ERA ART SAMPLES ---")
    for era in artist.eras[:3]:
        art = era.art_url[:80] + "..." if era.art_url and len(era.art_url) > 80 else era.art_url
        print(f"  {era.name[:40]:40s} → {art}")

    return artist


# Trackers
trackers = [
    ("https://yetracker.net/", "Ye"),
    ("https://docs.google.com/spreadsheets/d/1ogXipStHPpqEMgCDvxpWXQ7Yzly3YZx6riP25ChoxNM/htmlview", "Kendrick Lamar"),
    ("https://docs.google.com/spreadsheets/d/1-FxUYaxBqav0G6txAAixy7bhTGs86sItN_0_F8ekeKQ/htmlview", "Baby Keem"),
]

for url, name in trackers:
    try:
        verify_tracker(url, name)
    except Exception as e:
        print(f"  ERROR: {e}")
