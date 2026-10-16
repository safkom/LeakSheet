"""/stream fails fast for a provider known to be down, and /hosts reports it."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import src.api as api
from src import host_health, streaming

PILLOWS = "https://pillows.su/f/abc123"


@pytest.fixture
def clock(monkeypatch):
    # Scoped to host_health: the module-level time.time patch would reach the whole app.
    now = [1_000_000.0]
    monkeypatch.setattr(host_health, "time", SimpleNamespace(time=lambda: now[0]))
    return now


class AudioResponse:
    status_code = 200
    headers = {"content-type": "audio/mpeg", "content-length": "5"}
    url = "https://api.pillows.su/api/get/abc123"

    async def aiter_bytes(self, chunk_size=65536):
        yield b"hello"

    async def aclose(self):
        pass


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


def test_a_down_provider_is_retried_after_the_half_open_wait(api_client, monkeypatch, clock):
    host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")
    calls = []

    async def serves(url, *, range_header=None):
        calls.append(url)
        return AudioResponse()

    monkeypatch.setattr(api, "stream_audio", serves)
    clock[0] += 300 - 1
    assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 503
    assert calls == []

    clock[0] += 1
    hosts = {h["provider"]: h for h in api_client.get("/hosts").json()["hosts"]}
    assert hosts["pillows"]["status"] == "down"  # a let-through request is not yet a success
    assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 200
    assert len(calls) == 1
    assert host_health.down("pillows") is None


def test_a_failed_half_open_request_restarts_the_wait(api_client, monkeypatch, clock):
    host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")
    calls = []

    async def refused(url, *, range_header=None):
        calls.append(url)
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(api, "stream_audio", refused)
    clock[0] += 300
    assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 503
    assert len(calls) == 1
    assert host_health.down("pillows") is not None

    clock[0] += 300 - 1
    assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 503
    assert len(calls) == 1  # refused again without an upstream call

    clock[0] += 1
    assert api_client.get("/stream", params={"url": PILLOWS}).status_code == 503
    assert len(calls) == 2


@pytest.mark.parametrize("code", [400, 401, 403, 451])
def test_other_upstream_4xx_is_relayed_and_never_marks_the_provider_down(api_client, monkeypatch, code):
    async def refuses(url, *, range_header=None):
        raise streaming.UpstreamStatusError(code)

    monkeypatch.setattr(api, "stream_audio", refuses)
    for link in (PILLOWS, PILLOWS, "https://pillows.su/f/def456"):
        r = api_client.get("/stream", params={"url": link})
        assert r.status_code == code
        assert isinstance(r.json()["detail"], str)
    assert host_health.down("pillows") is None


@pytest.mark.parametrize(("provider", "links"), [
    ("pillows", [PILLOWS, "https://pillows.su/f/def456"]),
    ("gdrive", [
        "https://drive.google.com/file/d/abc123XYZ/view",
        "https://drive.google.com/file/d/def456XYZ/view",
    ]),
])
def test_non_media_bodies_never_mark_the_provider_down(api_client, monkeypatch, provider, links):
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.2")
    ))
    monkeypatch.setattr(streaming, "_get_shared_client", lambda: client)
    for link in (links[0], links[0], links[1]):
        assert api_client.get("/stream", params={"url": link}).status_code == 503
    assert host_health.down(provider) is None


def test_a_sniffed_non_media_body_never_marks_the_provider_down(api_client, monkeypatch):
    class PdfResponse(AudioResponse):
        headers = {"content-type": "application/octet-stream"}

        async def aiter_bytes(self, chunk_size=65536):
            yield b"%PDF-1.2\n" + b"x" * 64

    async def serves(url, *, range_header=None):
        return PdfResponse()

    monkeypatch.setattr(api, "stream_audio", serves)
    for link in (PILLOWS, PILLOWS, "https://pillows.su/f/def456"):
        assert api_client.get("/stream", params={"url": link}).status_code == 415
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
