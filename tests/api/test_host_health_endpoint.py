"""/stream fails fast for a provider known to be down, and /hosts reports it."""
from __future__ import annotations

import httpx

import src.api as api
from src import host_health, streaming

PILLOWS = "https://pillows.su/f/abc123"


def test_a_down_provider_is_refused_without_an_upstream_call(api_client, monkeypatch):
    host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")

    async def must_not_run(url, *, range_header=None):
        raise AssertionError("upstream contacted for a provider known to be down")

    monkeypatch.setattr(api, "stream_audio", must_not_run)
    r = api_client.get("/stream", params={"url": PILLOWS})
    assert r.status_code == 503
    assert r.headers["retry-after"] == "60"
    assert "pillows.su" in r.json()["detail"]


def test_a_connect_failure_marks_the_provider_down(api_client, monkeypatch):
    calls = []

    async def refused(url, *, range_header=None):
        calls.append(url)
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(api, "stream_audio", refused)
    assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 503
    assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 503
    assert len(calls) == 1  # the second request never waited on the dead host


def test_a_missing_file_does_not_mark_the_provider_down(api_client, monkeypatch):
    async def gone(url, *, range_header=None):
        raise streaming.UpstreamStatusError(404)

    monkeypatch.setattr(api, "stream_audio", gone)
    for _ in range(4):
        assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 404
    assert host_health.down("pillows") is None


def test_hosts_endpoint(api_client):
    host_health.record_failure("froste", "https://music.froste.lol/song/ab12", hard=True, error="ConnectTimeout")
    r = api_client.get("/hosts")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=30"
    hosts = {h["provider"]: h for h in r.json()["hosts"]}
    assert hosts["froste"]["status"] == "down"
    assert hosts["froste"]["host"] == "music.froste.lol"
    assert {"provider", "host", "status", "since", "checked"} <= set(hosts["froste"])


def test_stream_client_connect_timeout_is_short():
    assert streaming._get_shared_client().timeout.connect == 10.0
