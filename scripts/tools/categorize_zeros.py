"""Deep analysis of zero-song eras to categorize root causes for parser fixes."""
import json
from collections import Counter
from pathlib import Path

data = json.loads((Path(__file__).parent.parent / "results" / "live_validation.json").read_text())

# Categorize zero-song era names
patterns = {
    "navigation": [],      # "Skip to X", "Click to view..."
    "discord": [],         # Discord links
    "guidelines": [],      # "Unreleased Guidelines", "*New* Unreleased Guidelines"
    "updates": [],         # "22.10.2025 - Big findings", "added unknown section"
    "announcements": [],   # "PLEASE READ!", "Want to contribute?"
    "empty": [],           # Empty strings
    "meta_label": [],      # "Types", "Links", "MEGA Folder", "Editor(s)"
    "real_era": [],        # Genuine eras that lost song matching
}

def categorize(artist_name, era_name):
    lo = era_name.lower().strip()
    if not lo:
        return "empty"
    if lo.startswith("skip to"):
        return "navigation"
    if "click to view" in lo or "click here" in lo:
        return "navigation"
    if "discord" in lo:
        return "discord"
    if "guideline" in lo or "contribute" in lo:
        return "guidelines"
    if "please read" in lo or "please do not" in lo:
        return "announcements"
    # Date-prefixed updates like "22.10.2025 - Big findings"
    import re
    if re.match(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}", lo):
        return "updates"
    if lo.startswith("added ") or lo.startswith("updated ") or lo.startswith("removed "):
        return "updates"
    # Meta labels
    meta = {"types", "links", "link", "mega folder", "notes for me", "rules",
            "editor(s)", "editors", "type", "owner", "template", "key", "legend",
            "performance tracks", "suggest content to be added", "rest in power liam",
            "notes", "general information", "release date", "updates"}
    if lo in meta:
        return "meta_label"
    if "full compilation" in lo or "compilation of" in lo:
        return "meta_label"
    return "real_era"

for r in data:
    for issue in r["issues"]:
        if issue["check"] == "ZERO_SONG_ERAS":
            for d in issue.get("details", []):
                cat = categorize(r["artist_name"], d)
                patterns[cat].append((r["artist_name"], d))

print("="*70)
print("ZERO-SONG ERA CATEGORIZATION")
print("="*70)
for cat, items in sorted(patterns.items(), key=lambda x: -len(x[1])):
    print(f"\n{cat.upper()} ({len(items)}):")
    for artist, era in items[:15]:
        print(f"  [{artist}] {era[:70]}")
    if len(items) > 15:
        print(f"  ... and {len(items)-15} more")

# Focus on "real_era" — these are the ones we need to fix
real = patterns["real_era"]
print(f"\n{'='*70}")
print(f"GENUINE ERA MISMATCHES ({len(real)}):")
print(f"{'='*70}")
# Group by artist
from collections import defaultdict
by_artist = defaultdict(list)
for artist, era in real:
    by_artist[artist].append(era)
for artist in sorted(by_artist, key=lambda a: -len(by_artist[a])):
    eras = by_artist[artist]
    print(f"\n  {artist} ({len(eras)} zero-song eras):")
    for e in eras[:8]:
        print(f"    - {e[:80]}")
    if len(eras) > 8:
        print(f"    ... +{len(eras)-8} more")

# Summarize fixable categories
fixable_bogus = len(patterns["navigation"]) + len(patterns["discord"]) + \
                len(patterns["guidelines"]) + len(patterns["updates"]) + \
                len(patterns["announcements"]) + len(patterns["empty"]) + \
                len(patterns["meta_label"])
print(f"\n{'='*70}")
print(f"SUMMARY: {fixable_bogus} bogus eras (fixable via _looks_like_era_name)")
print(f"         {len(real)} genuine mismatches (need era-matching improvements)")
print(f"         TOTAL: {fixable_bogus + len(real)} zero-song eras")
