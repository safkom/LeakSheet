"""Opt-in mass validation over every tracker in the local artists.ndjson.

Marked ``live`` AND ``slow`` — it fetches hundreds of real sheets, so it's for
deliberate local sweeps (``pytest -m "live and slow"``), not CI. Skips entirely
when the gitignored ``Trackers/artists.ndjson`` registry is absent.

Unlike the old tests/test_all_spreadsheets.py (which reimplemented its own
validate_artist with its own thresholds — one of the divergent copies this
rebuild removed), it validates through the single ``_health.live_violations``.
"""

from __future__ import annotations

import json

import pytest

from src.config import TRACKERS_DIR
from src.fetcher import FetchError, async_fetch_and_parse
from tests._health import live_violations

pytestmark = [pytest.mark.live, pytest.mark.slow]

_NDJSON = TRACKERS_DIR / "artists.ndjson"


def _load_entries() -> list[tuple[str, str]]:
    if not _NDJSON.exists():
        return []
    entries: list[tuple[str, str]] = []
    for line in _NDJSON.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = e.get("url", "")
        if not url or "docs.google.com/document" in url:
            continue
        entries.append((e.get("name", "?"), url))
    return entries


ENTRIES = _load_entries()


@pytest.mark.skipif(not ENTRIES, reason="Trackers/artists.ndjson registry not present (gitignored)")
@pytest.mark.parametrize(("name", "url"), ENTRIES, ids=[n for n, _ in ENTRIES])
async def test_tracker_parses_healthy(name, url):
    try:
        artist = await async_fetch_and_parse(url, use_cache=True, cache_ttl=86400)
    except FetchError as e:
        pytest.skip(f"{name}: fetch failed: {e}")
    violations = live_violations(artist)
    assert not violations, f"{name} ({url}):\n  - " + "\n  - ".join(violations)
