"""Stale-cache prewarm (2026-07-20 review).

Selection: only parsed-cache entries inside the stale-while-revalidate gap
(older than DEFAULT_CACHE_TTL, younger than STALE_CACHE_TTL) qualify —
fresh entries don't need it, expired ones will cold-fetch anyway.
Execution: `_refresh_stale_once` funnels through `_background_revalidate`
(keeping its per-URL single-flight guard shared with request-triggered
revalidation). The loop itself sleeps before its first pass, so app startup
performs no network work.
"""

from __future__ import annotations

import json
import time

import pytest

import src.api as api
import src.fetcher as fetcher
from src.fetcher import _cache_key, _normalize_url, stale_parsed_cache_urls
from src.parser import parse_sheet
from tests.conftest import read_synthetic


def _seed_entry(url: str, *, age_s: float, parsed: bool = True) -> None:
    un = _normalize_url(url)
    fetcher._set_cache(un, "<html></html>", "T")
    if parsed:
        fetcher._set_cached_parsed(un, parse_sheet(read_synthetic("main_tab"), "SynthWave"))
    meta_path = fetcher.CACHE_DIR / f"{_cache_key(un)}.meta.json"
    meta = json.loads(meta_path.read_text())
    # Both: the HTML and the parse carry independent freshness signals, and an
    # entry that is genuinely old is old in both.
    aged = time.time() - age_s
    meta["timestamp"] = aged
    meta["parsed_timestamp"] = aged
    meta_path.write_text(json.dumps(meta))


class TestStaleSelection:
    def test_only_swr_gap_entries_selected(self):
        _seed_entry("https://docs.google.com/spreadsheets/d/FRESH1/htmlview", age_s=600)       # fresh
        _seed_entry("https://docs.google.com/spreadsheets/d/STALE1/htmlview", age_s=2 * 3600)  # gap
        _seed_entry("https://docs.google.com/spreadsheets/d/DEAD1/htmlview", age_s=48 * 3600)  # beyond SWR
        urls = stale_parsed_cache_urls(limit=10)
        assert [u for u in urls if "STALE1" in u]
        assert not [u for u in urls if "FRESH1" in u or "DEAD1" in u]

    def test_entries_without_parsed_json_ignored(self):
        # gid sub-pages cache html+meta but no parsed.json — not prewarm targets.
        _seed_entry("https://docs.google.com/spreadsheets/d/HTMLONLY/htmlview",
                    age_s=2 * 3600, parsed=False)
        assert stale_parsed_cache_urls(limit=10) == []

    def test_freshest_stale_first_and_capped(self):
        _seed_entry("https://docs.google.com/spreadsheets/d/OLDER1/htmlview", age_s=20 * 3600)
        _seed_entry("https://docs.google.com/spreadsheets/d/NEWER1/htmlview", age_s=2 * 3600)
        urls = stale_parsed_cache_urls(limit=1)
        assert len(urls) == 1 and "NEWER1" in urls[0]


class TestRefreshStaleOnce:
    async def test_revalidates_each_selected_url(self, monkeypatch):
        _seed_entry("https://docs.google.com/spreadsheets/d/STALE2/htmlview", age_s=2 * 3600)
        calls: list[str] = []

        async def fake_revalidate(url, artist_name):
            calls.append(url)

        monkeypatch.setattr(api, "_background_revalidate", fake_revalidate)
        n = await api._refresh_stale_once()
        assert n == 1
        assert len(calls) == 1 and "STALE2" in calls[0]

    async def test_noop_with_empty_cache(self, monkeypatch):
        async def boom(url, artist_name):
            raise AssertionError("must not revalidate anything")

        monkeypatch.setattr(api, "_background_revalidate", boom)
        assert await api._refresh_stale_once() == 0


class TestLifespanWiring:
    def test_prewarm_disabled_via_env(self, monkeypatch):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("LEAKSHEET_PREWARM", "0")
        created: list = []
        real_create_task = api.asyncio.create_task

        def tracking_create_task(coro, **kw):
            created.append(getattr(coro, "__name__", str(coro)))
            return real_create_task(coro, **kw)

        monkeypatch.setattr(api.asyncio, "create_task", tracking_create_task)
        with TestClient(api.app):
            pass
        assert "_prewarm_loop" not in created

    def test_prewarm_task_started_and_cancelled_cleanly(self, monkeypatch):
        from fastapi.testclient import TestClient

        monkeypatch.delenv("LEAKSHEET_PREWARM", raising=False)
        with TestClient(api.app):
            pass  # loop sleeps before first pass; shutdown must not hang/raise
