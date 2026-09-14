"""Every self-hosted tracker in the ArtistGrid feed is in the curated seed.

The image proxy trusts only the seed (plus LEAKSHEET_EXTRA_SHEET_HOSTS), not the
feed, because the feed is third-party. So a self-hosted tracker the feed lists
but the seed does not can be opened, but every era cover 403s. That is how the
A$AP Rocky tracker shipped with 45 grey covers. This fails when the feed gains
a new one, so the seed gets reviewed rather than silently falling behind.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import pytest

from src.config import curated_host_allowed
from src.fetcher import FetchError, fetch_artistgrid_entries

pytestmark = pytest.mark.live


async def test_every_self_hosted_feed_tracker_is_curated(monkeypatch):
    monkeypatch.delenv("LEAKSHEET_EXTRA_SHEET_HOSTS", raising=False)
    try:
        entries = await fetch_artistgrid_entries()
    except (FetchError, httpx.HTTPError) as e:
        pytest.skip(f"ArtistGrid feed unavailable: {e}")

    hosts = {(urlparse(e.url).hostname or "").lower() for e in entries}
    self_hosted = {h for h in hosts if h and not h.endswith(".google.com")}
    missing = sorted(h for h in self_hosted if not curated_host_allowed(h))
    assert not missing, (
        "self-hosted trackers the image proxy will refuse covers for — review and "
        f"add to _SHEET_HOST_SEED in src/config.py: {missing}"
    )
