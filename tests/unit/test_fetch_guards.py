"""Sheet bodies are read with a decoded-size cap, so a hostile host can't
stream or gzip-bomb a worker out of memory."""
import gzip

import httpx
import pytest

from src import fetcher


async def test_a_body_over_the_cap_is_refused(monkeypatch):
    monkeypatch.setattr(fetcher, "_MAX_SHEET_BYTES", 1000)
    bomb = gzip.compress(b"a" * 100_000)  # ~200 bytes on the wire
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=bomb, headers={"content-encoding": "gzip"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        # An httpx error, so a tab loop skips this one tab; the base-page
        # path maps it to NetworkError like any other upstream failure.
        with pytest.raises(fetcher.ResponseTooLarge):
            await fetcher._get_capped(client, "https://example.com/")


async def test_a_body_under_the_cap_reads_normally():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=gzip.compress(b"<table>ok"), headers={"content-encoding": "gzip"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        r = await fetcher._get_capped(client, "https://example.com/")
    assert r.status_code == 200 and r.text == "<table>ok"
    r.raise_for_status()


@pytest.mark.parametrize("exc", [httpx.ReadError("x"), httpx.RemoteProtocolError("x"), httpx.DecodingError("x")])
def test_every_upstream_failure_is_a_network_error(exc):
    # These used to escape unmapped and surface as a 500 "Internal error".
    with pytest.raises(fetcher.NetworkError):
        fetcher._raise_fetch_error(exc, "https://example.com/")


async def test_concurrent_unknown_hosts_share_one_feed_refresh(monkeypatch):
    import asyncio

    calls = []

    async def slow_fetch():
        calls.append(1)
        await asyncio.sleep(0.05)
        return []

    monkeypatch.setattr(fetcher, "fetch_artistgrid_entries", slow_fetch)
    monkeypatch.setattr(fetcher, "tracker_hosts_are_stale", lambda: True)
    monkeypatch.setattr(fetcher, "_host_refresh", None)
    await asyncio.gather(*(fetcher._refresh_tracker_hosts() for _ in range(5)))
    assert calls == [1]


@pytest.mark.parametrize("url,expected", [
    ("https://h:80/x", "https://h:80/x"),     # 80 is not https's default
    ("http://h:443/x", "http://h:443/x"),
    ("http://H:80/x", "http://h/x"),
    ("https://[::1]:8080/x", "https://[::1]:8080/x"),
])
def test_only_the_schemes_own_default_port_is_dropped(url, expected):
    assert fetcher._normalize_url(url) == expected
