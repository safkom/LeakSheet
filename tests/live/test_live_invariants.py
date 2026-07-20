"""Live invariant tests — fetch the locked public tracker set over the network
and assert the unified ``_health`` invariants.

Purpose: catch "a tracker changed its layout and the parser now silently drops
data" against the *latest* live data. Assertions are drift-tolerant
(``live_violations``: ratios and accounting identities, never exact counts) so
normal daily edits don't fail CI. A fetch/network failure is a ``skip`` (tracker
availability isn't the parser's fault); only a real parse break fails.

Not collected by the default run — the whole module is ``live``-marked. The CI
"live" job runs ``pytest -m live``; run it locally the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.fetcher import FetchError, async_fetch_and_parse
from tests._health import live_violations

pytestmark = pytest.mark.live

_URL_FILE = Path(__file__).resolve().parent.parent / "live_trackers.txt"


def _load_urls() -> list[str]:
    if not _URL_FILE.exists():
        return []
    return [
        ln.strip()
        for ln in _URL_FILE.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


LIVE_URLS = _load_urls()


@pytest.mark.skipif(not LIVE_URLS, reason="no URLs in tests/live_trackers.txt")
@pytest.mark.parametrize("url", LIVE_URLS)
async def test_live_tracker_parses_healthy(url):
    try:
        artist = await async_fetch_and_parse(url, use_cache=False, write_cache=False)
    except FetchError as e:
        pytest.skip(f"fetch failed (tracker availability / network): {e}")

    violations = live_violations(artist)
    assert not violations, (
        f"{url} → {artist.name!r} parsed with invariant violations:\n  - "
        + "\n  - ".join(violations)
    )
