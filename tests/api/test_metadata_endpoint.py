"""Contract tests for GET /metadata (provider-metadata proxy)."""

from __future__ import annotations

import pytest

import src.api as api

PILLOWS_BLOB = (
    "FILE FORMAT INFO:CONTAINER: FLACCODEC: FLACDURATION: 210.5s"
    "BITRATE: 1024kbpsSAMPLE RATE: 44100HzLOSSLESS: true"
    "COMMON INFO:TITLE: Some Song"
)


class FakeResp:
    def __init__(self, *, text="", json_data=None, status=200):
        self.text = text
        self._json = json_data
        self.status_code = status

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.calls = 0

    async def get(self, url, headers=None):
        self.calls += 1
        return self.resp


@pytest.fixture(autouse=True)
def _fresh_metadata_cache(monkeypatch):
    # The metadata cache is a module global — reset it so tests don't leak hits.
    monkeypatch.setattr(api, "_metadata_cache", api._TTLCache(ttl=3600.0, max_entries=500))


def _install(monkeypatch, resp):
    fake = FakeClient(resp)
    monkeypatch.setattr(api, "_get_shared_client", lambda: fake)
    return fake


class TestMetadataEndpoint:
    def test_unsupported_host_404(self, api_client):
        r = api_client.get("/metadata", params={"url": "https://example.com/x.mp3"})
        assert r.status_code == 404

    def test_pillows_metadata_parsed(self, api_client, monkeypatch):
        _install(monkeypatch, FakeResp(text=PILLOWS_BLOB))
        r = api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "miss"
        data = r.json()
        assert data["provider"] == "pillows"
        assert data["container"] == "FLAC"
        assert data["lossless"] is True

    def test_second_call_is_cached(self, api_client, monkeypatch):
        fake = _install(monkeypatch, FakeResp(text=PILLOWS_BLOB))
        api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        r2 = api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        assert r2.headers["X-Cache-Status"] == "hit"
        assert fake.calls == 1  # second request served from cache

    def test_froste_metadata_parsed(self, api_client, monkeypatch):
        _install(monkeypatch, FakeResp(json_data={
            "estimatedBitrate": 255.6, "frequencyCutoff": 19.94, "qualityMismatch": False,
        }))
        r = api_client.get("/metadata", params={"url": "https://music.froste.lol/song/deadbeef"})
        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == "froste"
        assert data["bitrate"] == "256kbps"

    def test_provider_error_is_502(self, api_client, monkeypatch):
        _install(monkeypatch, FakeResp(text="", status=500))
        r = api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        assert r.status_code == 502
