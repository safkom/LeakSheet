"""Contract test for POST /cache/clear.

The endpoint is privileged: CORS is open and it mutates shared server state, so
it must not be callable by an arbitrary page. It requires the ``X-Admin-Token``
header to match ``LEAKSHEET_ADMIN_TOKEN``; when that env var is unset the
endpoint is disabled (fail closed).
"""

from __future__ import annotations

import src.api as api

_TOKEN = "s3cret-admin-token"


class TestCacheClearAuth:
    def test_disabled_when_token_unset(self, api_client, monkeypatch):
        monkeypatch.delenv("LEAKSHEET_ADMIN_TOKEN", raising=False)
        r = api_client.post("/cache/clear")
        assert r.status_code == 503

    def test_missing_token_rejected_when_configured(self, api_client, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_ADMIN_TOKEN", _TOKEN)
        r = api_client.post("/cache/clear")
        assert r.status_code == 401

    def test_wrong_token_rejected(self, api_client, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_ADMIN_TOKEN", _TOKEN)
        r = api_client.post("/cache/clear", headers={"X-Admin-Token": "nope"})
        assert r.status_code == 401

    def test_non_ascii_configured_token_does_not_crash(self, api_client, monkeypatch):
        # hmac.compare_digest raises TypeError on non-ASCII str; the handler
        # compares bytes, so a non-ASCII token yields a clean 401 (not a 500).
        monkeypatch.setenv("LEAKSHEET_ADMIN_TOKEN", "sécrét")
        r = api_client.post("/cache/clear", headers={"X-Admin-Token": "wrong"})
        assert r.status_code == 401


class TestCacheClearAuthorized:
    def test_clears_cache_files_and_reports_count(self, api_client, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_ADMIN_TOKEN", _TOKEN)
        # The autouse _isolate_cache fixture points CACHE_DIR at a tmp dir.
        (api.CACHE_DIR / "abc.html").write_text("x")
        (api.CACHE_DIR / "abc.meta.json").write_text("{}")
        (api.CACHE_DIR / "img_z.bin").write_bytes(b"y")

        r = api_client.post("/cache/clear", headers={"X-Admin-Token": _TOKEN})
        assert r.status_code == 200
        assert r.json() == {"cleared": 3, "skipped": 0}
        assert list(api.CACHE_DIR.iterdir()) == []

    def test_clear_empty_cache_is_zero(self, api_client, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_ADMIN_TOKEN", _TOKEN)
        r = api_client.post("/cache/clear", headers={"X-Admin-Token": _TOKEN})
        assert r.status_code == 200
        assert r.json()["cleared"] == 0
