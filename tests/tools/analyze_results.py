"""Analyze saved live_validation.json results."""

import json
from collections import Counter
from pathlib import Path

data = json.loads((Path(__file__).parent.parent / "results" / "live_validation.json").read_text())

statuses = Counter(r["status"] for r in data)
print("STATUS BREAKDOWN:")
for s, c in statuses.most_common():
    print(f"  {s}: {c}")

# Issue type breakdown
issue_types = Counter()
for r in data:
    for i in r["issues"]:
        if i["severity"] != "INFO":
            issue_types[i["check"]] += 1

print(f"\nISSUE TYPE FREQUENCY (excl. INFO):")
for t, c in issue_types.most_common():
    print(f"  {t}: {c}")

# Error type breakdown
errors = [r for r in data if r["status"] == "error"]
error_types = Counter(r["error_type"] for r in errors)
print(f"\nERROR TYPES ({len(errors)} total):")
for t, c in error_types.most_common():
    print(f"  {t}: {c}")

# Critical trackers detail
criticals = [r for r in data if r["status"] == "critical"]
print(f"\n{'='*70}")
print(f"CRITICAL TRACKERS ({len(criticals)}):")
print(f"{'='*70}")
for r in criticals:
    crit_issues = [i for i in r["issues"] if i["severity"] == "CRITICAL"]
    checks = ", ".join(i["check"] for i in crit_issues)
    print(f"\n  {r['artist_name']:<45} {r['eras']:3d}E {r['songs']:4d}S  [{checks}]")
    for i in crit_issues:
        for d in (i.get("details") or [])[:4]:
            print(f"    - {d[:80]}")

# Overall stats
total_eras = sum(r["eras"] for r in data)
total_songs = sum(r["songs"] for r in data)
total_versions = sum(r["versions"] for r in data)
print(f"\n{'='*70}")
print(f"AGGREGATE: {len(data)} spreadsheets, {total_eras} eras, {total_songs} songs, {total_versions} versions")

# ZERO_SONG_ERAS detail — categorize the types
all_zero_details = []
for r in data:
    for i in r["issues"]:
        if i["check"] == "ZERO_SONG_ERAS":
            for d in (i.get("details") or []):
                all_zero_details.append((r["artist_name"], d))

print(f"\nZERO-SONG ERA NAMES ({len(all_zero_details)} across all trackers):")
# Group by pattern
nav = [d for _, d in all_zero_details if d.lower().startswith("skip to")]
discord = [d for _, d in all_zero_details if "discord" in d.lower()]
guidelines = [d for _, d in all_zero_details if "guideline" in d.lower() or "contribute" in d.lower()]
update = [d for _, d in all_zero_details if "update" in d.lower() or "added" in d.lower()]
other = [(a, d) for a, d in all_zero_details 
         if not d.lower().startswith("skip to") 
         and "discord" not in d.lower()
         and "guideline" not in d.lower()
         and "contribute" not in d.lower()
         and "update" not in d.lower()
         and "added" not in d.lower()]
print(f"  'Skip to...' navigation: {len(nav)}")
print(f"  Discord links/messages: {len(discord)}")
print(f"  Guidelines/contribute: {len(guidelines)}")
print(f"  Update/changelog: {len(update)}")
print(f"  Other (genuine mismatches): {len(other)}")
print(f"\n  Top 30 'other' zero-song eras:")
for artist, era_name in other[:30]:
    print(f"    [{artist}] {era_name[:70]}")
