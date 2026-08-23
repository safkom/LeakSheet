"""Draft a ground-truth label file for one tracker, for a human to verify.

    python3 -m tests.quality.make_label osamason --family flat-era

Writes tests/quality/labels/<slug>.json from current parser output.

THE DRAFT IS NOT GROUND TRUTH. It is a form with the fields pre-filled, so a
human can compare each value against the rendered sheet and correct it. A draft
committed unread is a snapshot of the parser's own behaviour, which is exactly
the self-referential baseline this suite exists to replace — and it would pass
forever, including through a regression.

Verify against the real sheet:
  * era names, their order, and which of them have cover art
  * per-era song counts
  * every spot_check value

then delete the "unverified" flag.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.parser import parse_sheet  # noqa: E402

LABELS_DIR = Path(__file__).parent / "labels"
CORPUS_DIR = os.environ.get("LEAKSHEET_CORPUS", ".cache")

# Fields worth spot-checking: the ones a mislabelled column corrupts silently.
SPOT_FIELDS = ("quality", "available_length", "track_length", "leak_date",
               "producers", "featuring", "rating", "og_filename")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def _candidates(needle: str):
    """Cached tabs whose title or URL contains *needle*, best-scoring first."""
    found = []
    for path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.html"))):
        meta_path = path.replace(".html", ".meta.json")
        if not os.path.exists(meta_path):
            continue
        try:
            meta = json.load(open(meta_path))
        except (OSError, ValueError):
            continue
        title, url = meta.get("title", ""), meta.get("url", "")
        if needle.lower() not in f"{title} {url}".lower():
            continue
        raw = open(path, "rb").read()
        try:
            artist = parse_sheet(raw.decode("utf-8", errors="replace"), title, url)
        except Exception:  # noqa: BLE001
            continue
        found.append(((1 if artist.total_songs else 0, artist.total_songs,
                       len(artist.eras)), raw, title, url, artist))
    found.sort(key=lambda f: f[0], reverse=True)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("needle", help="substring of the tracker title or URL")
    ap.add_argument("--family", default="unknown",
                    help="layout family, e.g. flat-era, discography-stats")
    ap.add_argument("--spot", type=int, default=6, help="how many spot checks to draft")
    args = ap.parse_args()

    found = _candidates(args.needle)
    if not found:
        print(f"no cached tab matching {args.needle!r} in {CORPUS_DIR}", file=sys.stderr)
        return 1
    _, raw, title, url, artist = found[0]
    if len(found) > 1:
        print(f"note: {len(found)} tabs matched; drafting the highest-scoring one "
              f"({artist.total_songs} songs). Confirm it is the tab you meant.")

    label = {
        "unverified": True,
        "_comment": "DRAFT from parser output. Verify every value against the "
                    "rendered sheet, then remove the 'unverified' flag.",
        "artist": artist.name,
        "layout_family": args.family,
        "source_url": url,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "eras": [
            {
                "name": era.name,
                "songs": sum(len(s.songs) for s in era.sections),
                "has_art": bool(era.art_url),
            }
            for era in artist.eras
        ],
        "spot_checks": _draft_spot_checks(artist, args.spot),
    }

    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    out = LABELS_DIR / f"{_slug(artist.name)}.json"
    with open(out, "w") as fh:
        json.dump(label, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {out}  ({len(label['eras'])} eras, "
          f"{len(label['spot_checks'])} spot checks) — NOW VERIFY IT")
    return 0


def _draft_spot_checks(artist, want: int) -> list[dict]:
    """Pick songs with the most populated fields — they exercise the most columns."""
    out = []
    for era in artist.eras:
        for section in era.sections:
            for song in section.songs:
                if not song.versions:
                    continue
                v = song.versions[0]
                filled = [f for f in SPOT_FIELDS if getattr(v, f, None) not in (None, "", [])]
                if len(filled) < 3:
                    continue
                out.append({
                    "era": era.name,
                    "song": song.base_name,
                    "field": filled[0],
                    "expect": getattr(v, filled[0]),
                })
                break
        if len(out) >= want:
            break
    return out[:want]


if __name__ == "__main__":
    raise SystemExit(main())
