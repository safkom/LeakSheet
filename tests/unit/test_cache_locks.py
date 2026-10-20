import multiprocessing
import os
import time

import httpx
import pytest

import src.fetcher as fetcher
from src.fetcher import NoTablesError, _cache_key, _entry_lock, async_fetch_sheet_html

URL = "https://docs.google.com/spreadsheets/d/SYNTH123/htmlview"


@pytest.mark.asyncio
async def test_gid_fetch_without_table_is_not_cached(monkeypatch):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, html="<html>nothing</html>"))
    )
    monkeypatch.setattr(fetcher, "_get_sheets_client", lambda: client)
    with pytest.raises(NoTablesError):
        await async_fetch_sheet_html(URL, gid="5")
    assert not list(fetcher.CACHE_DIR.glob("*.html"))


def test_eviction_keeps_host_health_and_drops_idle_orphan_locks(monkeypatch):
    fetcher.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    health = fetcher.CACHE_DIR / "host_health.json"
    health.write_text("{}" * 100)
    orphan = fetcher.CACHE_DIR / "deadbeef.meta.lock"
    orphan.write_text("")
    old = time.time() - 2 * fetcher._ORPHAN_TMP_AGE_S
    os.utime(orphan, (old, old))
    held = fetcher.CACHE_DIR / "cafe.meta.lock"
    held.write_text("")
    os.utime(held, (old, old))
    monkeypatch.setattr(fetcher, "_SHEET_CACHE_MAX_BYTES", 1)
    with _entry_lock("cafe"):
        fetcher._evict_sheet_cache()
        assert held.exists()
    assert health.exists()
    assert not orphan.exists()


def _hold(key, cache_dir, started, release):
    fetcher.CACHE_DIR = cache_dir
    with _entry_lock(key):
        started.set()
        release.wait(10)


def test_entry_lock_excludes_across_processes():
    ctx = multiprocessing.get_context("fork")
    started, release = ctx.Event(), ctx.Event()
    key = _cache_key(URL)
    proc = ctx.Process(target=_hold, args=(key, fetcher.CACHE_DIR, started, release))
    proc.start()
    try:
        assert started.wait(10)
        import fcntl

        with open(fetcher.CACHE_DIR / f"{key}.meta.lock", "a") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release.set()
        proc.join(10)
        with _entry_lock(key):  # free again once the holder exits
            pass
    finally:
        release.set()
        proc.join(5)
