"""Contract test for POST /cache/clear."""

from __future__ import annotations

import src.api as api


class TestCacheClear:
    def test_clears_cache_files_and_reports_count(self, api_client):
        # The autouse _isolate_cache fixture points CACHE_DIR at a tmp dir.
        (api.CACHE_DIR / "abc.html").write_text("x")
        (api.CACHE_DIR / "abc.meta.json").write_text("{}")
        (api.CACHE_DIR / "img_z.bin").write_bytes(b"y")

        r = api_client.post("/cache/clear")
        assert r.status_code == 200
        assert r.json()["cleared"] == 3
        assert list(api.CACHE_DIR.iterdir()) == []

    def test_clear_empty_cache_is_zero(self, api_client):
        r = api_client.post("/cache/clear")
        assert r.status_code == 200
        assert r.json()["cleared"] == 0
