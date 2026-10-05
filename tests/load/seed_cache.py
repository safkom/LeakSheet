"""Seed a parse cache for the k6 load test: one synthetic tracker, no network.

The synthetic main tab is repeated into a few hundred eras (a mid-size tracker, a few
MB on the wire), so the warm /sheet path is measured on a realistic payload.

Usage: python -m tests.load.seed_cache CACHE_DIR
"""

from __future__ import annotations

import sys
from pathlib import Path

from src import fetcher
from src.parser import parse_sheet

# A docs.google.com URL passes the /sheet host allowlist; the cache answers before any fetch.
SHEET_URL = "https://docs.google.com/spreadsheets/d/k6-synthetic-tracker/htmlview"
ERA_COPIES = 300


def main(cache_dir: str) -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "main_tab.html"
    artist = parse_sheet(fixture.read_text(encoding="utf-8"), "K6 Synthetic")
    artist.eras = [
        era.model_copy(update={"name": f"{era.name} {i}"})
        for i in range(ERA_COPIES)
        for era in artist.eras
    ]
    fetcher.CACHE_DIR = Path(cache_dir)
    fetcher.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fetcher._set_cached_parsed(fetcher._normalize_url(SHEET_URL), artist)
    body, etag = artist._wire
    print(f"seeded {SHEET_URL}: {len(artist.eras)} eras, {len(body) / 1e6:.1f} MB, etag {etag[:12]}")


if __name__ == "__main__":
    main(sys.argv[1])
