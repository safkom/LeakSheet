"""Live-layer fixtures.

pytest-asyncio runs every coroutine test on a FRESH event loop, but the
production fetch/stream stacks cache module-global ``httpx.AsyncClient``s
bound to whichever loop first created them (fine under uvicorn's single
loop). Without a reset, the second live test onward dies with
"RuntimeError: Event loop is closed" before any network I/O happens.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_shared_clients(monkeypatch):
    import src.fetcher as fetcher
    import src.streaming as streaming

    monkeypatch.setattr(fetcher, "_sheets_client", None)
    monkeypatch.setattr(streaming, "_shared_client", None)
