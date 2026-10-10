"""Per-provider stream health: transitions, the shared file, and the recovery prober.

A dead provider made every play attempt wait out a connect timeout. Health is shared
through one file because the API runs several workers.
"""
from __future__ import annotations

import fcntl

import httpx
import pytest

from src import fetcher, host_health
from src.streaming import UpstreamStatusError

PILLOWS = "https://pillows.su/f/abc"
PILLOWS_2 = "https://pillows.su/f/def"


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(host_health.time, "time", lambda: now[0])
    return now


def test_provider_of_each_supported_link():
    assert host_health.provider_for("https://pillows.su/f/abc") == "pillows"
    assert host_health.provider_for("https://www.krakenfiles.com/view/AbC/file.html") == "kraken"
    assert host_health.provider_for("https://music.froste.lol/song/abc123") == "froste"
    assert host_health.provider_for("https://imgur.gg/f/abc") == "imgur"
    assert host_health.provider_for("https://pixeldrain.com/u/abc") == "pixeldrain"
    assert host_health.provider_for("https://drive.google.com/file/d/abc/view") == "gdrive"
    assert host_health.provider_for("https://example.com/a.mp3") is None


def test_a_connect_failure_marks_the_provider_down_at_once(clock):
    host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")
    down = host_health.down("pillows")
    assert down is not None and down["host"] == "pillows.su"


def test_soft_failures_need_three_across_two_links(clock):
    for _ in range(3):
        host_health.record_failure("pillows", PILLOWS, hard=False, error="HTTP 500")
    assert host_health.down("pillows") is None  # one bad file, not a dead host
    host_health.record_failure("pillows", PILLOWS_2, hard=False, error="HTTP 500")
    assert host_health.down("pillows") is not None


def test_old_soft_failures_expire(clock):
    host_health.record_failure("pillows", PILLOWS, hard=False, error="HTTP 500")
    host_health.record_failure("pillows", PILLOWS_2, hard=False, error="HTTP 500")
    clock[0] += 121
    host_health.record_failure("pillows", PILLOWS, hard=False, error="HTTP 500")
    assert host_health.down("pillows") is None


def test_a_success_marks_it_up(clock):
    host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")
    host_health.record_success("pillows")
    assert host_health.down("pillows") is None


def test_state_is_shared_through_the_file(clock):
    host_health.record_failure("froste", "https://music.froste.lol/song/ab", hard=True, error="ConnectTimeout")
    host_health._cache = None  # what another worker sees: only the file
    assert host_health.down("froste") is not None
    assert (fetcher.CACHE_DIR / "host_health.json").exists()


def test_snapshot_lists_every_provider(clock):
    host_health.record_failure("froste", "https://music.froste.lol/song/ab", hard=True, error="ConnectTimeout")
    hosts = {h["provider"]: h for h in host_health.snapshot()}
    assert set(hosts) == set(host_health.PROVIDERS)
    assert hosts["froste"]["status"] == "down" and hosts["froste"]["host"] == "music.froste.lol"
    assert hosts["pillows"]["status"] == "up"


class TestProber:
    async def test_probe_success_marks_up(self, clock, monkeypatch):
        host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")
        seen = []

        async def fake_stream_audio(url, *, range_header=None):
            seen.append((url, range_header))
            return httpx.Response(206)

        monkeypatch.setattr(host_health, "stream_audio", fake_stream_audio)
        await host_health.probe_once()
        assert host_health.down("pillows") is None
        assert seen == [("https://api.pillows.su/api/get/abc", "bytes=0-0")]

    async def test_a_404_means_the_host_answers(self, clock, monkeypatch):
        host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")

        async def gone(url, *, range_header=None):
            raise UpstreamStatusError(404)

        monkeypatch.setattr(host_health, "stream_audio", gone)
        await host_health.probe_once()
        assert host_health.down("pillows") is None

    async def test_still_unreachable_stays_down(self, clock, monkeypatch):
        host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")

        async def dead(url, *, range_header=None):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(host_health, "stream_audio", dead)
        await host_health.probe_once()
        assert host_health.down("pillows") is not None

    async def test_one_broken_file_cannot_keep_a_healthy_host_down(self, clock, monkeypatch):
        # Down on soft failures across two links; the first link's file stays broken.
        for link in (PILLOWS, PILLOWS_2, PILLOWS):
            host_health.record_failure("pillows", link, hard=False, error="HTTP 500")
        assert host_health.down("pillows") is not None

        async def first_file_broken(url, *, range_header=None):
            if url.endswith("/abc"):
                raise UpstreamStatusError(500)
            return httpx.Response(206)

        monkeypatch.setattr(host_health, "stream_audio", first_file_broken)
        await host_health.probe_once()
        assert host_health.down("pillows") is None

    async def test_only_the_lock_holder_probes(self, clock, monkeypatch):
        host_health.record_failure("pillows", PILLOWS, hard=True, error="ConnectError")
        called = []

        async def fake_stream_audio(url, *, range_header=None):
            called.append(url)
            return httpx.Response(206)

        monkeypatch.setattr(host_health, "stream_audio", fake_stream_audio)
        fetcher.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(fetcher.CACHE_DIR / "host_health.probe.lock", "a") as other_worker:
            fcntl.flock(other_worker, fcntl.LOCK_EX)
            await host_health.probe_once()
        assert called == []
