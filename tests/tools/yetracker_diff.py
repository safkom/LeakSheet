#!/usr/bin/env python3
"""Diff our Ye parse against yetracker.cc, an independent parse of the same sheet.

yetracker.cc publishes the Ye tracker as JSON (/api/manifest, /api/tab/<name>).
Two parsers agreeing row for row is strong evidence; where they disagree, one
of them is wrong — check the sheet before assuming it is us (theirs files
"(ref. X) (prod. Y)" credit lines as alt titles, for one).

Opt-in and never in CI: it depends on a third-party site.

Usage:
    uv run python -m tests.tools.yetracker_diff            # parse locally, live
    uv run python -m tests.tools.yetracker_diff --api URL  # diff a deployed API instead
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

YE_URL = "https://yetracker.net/"
ORACLE = "https://yetracker.cc/api"
EMOJI = re.compile(r"^[\s⭐✨\U0001F5D1️\U0001F3C6\U0001F3C5\U0001F947\U0001F949\U0001F916\U0001F48E]+")
ROW_FIELDS = ("track_length", "file_date", "leak_date", "available_length", "quality")


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def ours(api: str | None) -> dict:
    if api:
        r = httpx.post(f"{api.rstrip('/')}/sheet", json={"url": YE_URL}, timeout=180)
        r.raise_for_status()
        return r.json()
    from src.fetcher import async_fetch_and_parse

    artist = asyncio.run(async_fetch_and_parse(YE_URL, use_cache=False, write_cache=False))
    return json.loads(artist.model_dump_json())


def oracle(tab: str) -> dict:
    return httpx.get(f"{ORACLE}/tab/{tab}", timeout=60).json()


def diff_main(us: dict, them: dict) -> None:
    our_eras = {e["name"]: e for e in us["eras"]}
    their_eras = {e["name"]: e for e in them["eras"]}
    print(f"eras: ours {len(our_eras)}, theirs {len(their_eras)}")
    for name in sorted(set(our_eras) ^ set(their_eras)):
        print(f"  only {'ours' if name in our_eras else 'theirs'}: {name!r}")

    matched = unmatched = 0
    fields: Counter = Counter()
    examples: dict[str, list] = {}
    for name, te in their_eras.items():
        oe = our_eras.get(name)
        if not oe:
            continue
        index: dict[tuple, list] = {}
        for sec in oe["sections"]:
            for song in sec["songs"]:
                for v in song["versions"]:
                    title = v["name"] + (f" [{v['version_tag']}]" if v.get("version_tag") else "")
                    index.setdefault((norm(EMOJI.sub("", title)), norm(v["notes"])[:60]), []).append(v)
        section_names = {norm(s["name"]) for s in oe["sections"]}
        for t in te["tracks"]:
            key = (norm(EMOJI.sub("", t["name"]["title"])), norm(t["notes"])[:60])
            if index.get(key):
                v = index[key].pop(0)
                matched += 1
                for f in ROW_FIELDS:
                    if (t.get(f) or None) != (v.get(f) or None):
                        fields[f] += 1
                        examples.setdefault(f, []).append((name, t["name"]["title"], t.get(f), v.get(f)))
            elif norm(t["name"]["title"]) in section_names and not t.get("available_length"):
                matched += 1  # a sub-era label row: ours is a Section
            else:
                unmatched += 1
                examples.setdefault("unmatched", []).append((name, t["name"]["raw"][:70]))
    print(f"main rows: {matched} matched, {unmatched} unmatched")
    for f, n in fields.most_common():
        print(f"  {f}: {n} differ, e.g. {examples[f][:3]}")
    for ex in examples.get("unmatched", [])[:15]:
        print(f"  unmatched: {ex}")


def diff_tab(us: dict, kind: str, them: dict) -> None:
    ours_rows = next((t["entries"] for t in us.get("tabs", []) if t["kind"] == kind), [])
    theirs_rows = [t for e in them["eras"] for t in e.get("tracks", [])]
    our_sections = Counter(r.get("section") or "" for r in ours_rows)
    their_sections = Counter(r.get("subsection") or "" for r in theirs_rows)
    print(f"{kind}: ours {len(ours_rows)} rows, theirs {len(theirs_rows)}")
    for name in sorted(set(our_sections) | set(their_sections)):
        if our_sections[name] != their_sections[name]:
            print(f"  section {name!r}: ours {our_sections[name]}, theirs {their_sections[name]}")
    with_length = sum(1 for r in ours_rows if r.get("length"))
    print(f"  length: ours {with_length}, theirs {sum(1 for r in theirs_rows if r.get('track_length'))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", help="diff a deployed API (e.g. https://sheets.safko.eu/api)")
    args = ap.parse_args()
    manifest = httpx.get(f"{ORACLE}/manifest", timeout=30).json()
    print(f"yetracker.cc last updated {manifest.get('lastUpdated')}")
    us = ours(args.api)
    diff_main(us, oracle("main"))
    for kind in ("stems", "misc", "released"):
        diff_tab(us, kind, oracle(kind))


if __name__ == "__main__":
    main()
