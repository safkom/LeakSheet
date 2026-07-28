"""Opt-in mass validation over the live TrackerHub registry.

Marked ``live`` AND ``slow`` — it fetches the TrackerHub master sheet, then
every up-to-date tracker it lists (dozens of real sheets). For deliberate local
sweeps (``pytest -m "live and slow"``), not CI.

The registry is the **live `/trackers` TrackerHub feed** (the old
``Trackers/artists.ndjson`` file is deprecated). The fetch happens inside the
test — never at collection time — so offline runs never touch the network.

Validation goes through the single ``_health.live_violations`` definition
(drift-tolerant: only genuine parse breaks fail; fetch failures are reported as
skipped trackers, not errors).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from src.parser import parse_trackerhub
from src.config import TRACKERHUB_URL
from src.fetcher import FetchError, async_fetch_and_parse
from tests._health import live_violations

pytestmark = [pytest.mark.live, pytest.mark.slow]

_CONCURRENCY = 4  # polite to Google


async def _sweep() -> tuple[list[str], list[str], int]:
    """Return (violation_reports, fetch_skips, ok_count) over TrackerHub."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as hub_client:
        resp = await hub_client.get(TRACKERHUB_URL, headers={"Accept": "text/html"})
        resp.raise_for_status()
    entries = parse_trackerhub(resp.text)
    targets = [e for e in entries if e.up_to_date] or entries
    assert targets, "TrackerHub parsed to zero entries — endpoint or parser broke"

    sem = asyncio.Semaphore(_CONCURRENCY)
    violations: list[str] = []
    skips: list[str] = []
    ok = 0

    async def _one(entry) -> None:
        nonlocal ok
        async with sem:
            try:
                artist = await async_fetch_and_parse(
                    entry.url, artist_name=entry.name, use_cache=True, cache_ttl=86400
                )
            except FetchError as e:
                skips.append(f"{entry.name}: fetch failed: {str(e)[:120]}")
                return
            except Exception as e:  # noqa: BLE001 — a crash on ONE tracker is a finding
                violations.append(f"{entry.name} ({entry.url}): parser crashed: {type(e).__name__}: {e}")
                return
        found = live_violations(artist)
        if found:
            violations.append(
                f"{entry.name} ({entry.url}):\n    - " + "\n    - ".join(found)
            )
        else:
            ok += 1

    await asyncio.gather(*[_one(e) for e in targets])
    return violations, skips, ok


async def test_trackerhub_trackers_parse_healthy():
    violations, skips, ok = await _sweep()
    print(f"\nTrackerHub sweep: {ok} healthy, {len(violations)} violating, {len(skips)} unfetchable")
    for s in skips:
        print(f"  [skip] {s}")
    assert not violations, (
        f"{len(violations)} tracker(s) violate parse-health invariants "
        f"({ok} healthy, {len(skips)} skipped):\n" + "\n".join(violations)
    )
