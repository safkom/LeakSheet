"""Contract tests for GET /metadata (provider-metadata proxy)."""

from __future__ import annotations


import asyncio
import json
import logging

import httpx

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

    async def aiter_bytes(self):
        body = self.text or json.dumps(self._json or "")
        for i in range(0, len(body), 1024):
            self.bytes_read = i + 1024
            yield body[i : i + 1024].encode()

    async def aclose(self):
        pass


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.calls = 0
        self.timeout = None

    def build_request(self, method, url, headers=None, timeout=None):
        self.calls += 1
        self.timeout = timeout
        return url

    async def send(self, request, stream=False):
        return self.resp


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

    def test_provider_error_is_503(self, api_client, monkeypatch):
        _install(monkeypatch, FakeResp(text="", status=500))
        r = api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        assert r.status_code == 503


class _HangingClient:
    """A provider that accepts the connection and never answers (get, or the HEAD fallback)."""

    def __init__(self, get_resp=None):
        self.get_resp = get_resp

    def build_request(self, method, url, headers=None, timeout=None):
        return url

    async def send(self, request, stream=False):
        if self.get_resp is not None:
            return self.get_resp
        await asyncio.Event().wait()

    async def head(self, url, headers=None, timeout=None, follow_redirects=None):
        await asyncio.Event().wait()


class TestMetadataIsBounded:
    def test_a_huge_body_is_read_only_up_to_the_cap(self, api_client, monkeypatch):
        resp = FakeResp(text="x" * (5 * 1024 * 1024))
        _install(monkeypatch, resp)
        r = api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        assert r.status_code == 200
        assert resp.bytes_read <= 512 * 1024 + 1024

    def test_calls_carry_a_short_connect_timeout(self, api_client, monkeypatch):
        fake = _install(monkeypatch, FakeResp(text=PILLOWS_BLOB))
        api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        assert fake.timeout == httpx.Timeout(10.0, connect=5.0)

    def test_hanging_provider_is_503_and_not_an_error_log(self, api_client, monkeypatch, caplog):
        monkeypatch.setattr(api, "_METADATA_DEADLINE_S", 0.05)
        monkeypatch.setattr(api, "_get_shared_client", lambda: _HangingClient())
        with caplog.at_level(logging.INFO):
            r = api_client.get("/metadata", params={"url": "https://music.froste.lol/song/deadbeef"})
        assert r.status_code == 503
        assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]

    def test_hanging_head_fallback_is_503(self, api_client, monkeypatch):
        # The .txt endpoint 404s, then the HEAD fallback hangs: one deadline covers both calls.
        monkeypatch.setattr(api, "_METADATA_DEADLINE_S", 0.05)
        monkeypatch.setattr(
            api, "_get_shared_client", lambda: _HangingClient(FakeResp(text="", status=404))
        )
        r = api_client.get("/metadata", params={"url": "https://pillows.su/f/abc"})
        assert r.status_code == 503
