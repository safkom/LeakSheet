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
    assert r.status_code == 200
    assert r.text == "<table>ok"
    r.raise_for_status()


@pytest.mark.parametrize("exc", [httpx.ReadError("x"), httpx.RemoteProtocolError("x"), httpx.DecodingError("x")])
def test_every_upstream_failure_is_a_network_error(exc):
    # These used to escape unmapped and surface as a 500 "Internal error".
    with pytest.raises(fetcher.NetworkError):
        fetcher._raise_fetch_error(exc, "https://example.com/")


@pytest.mark.parametrize(("status", "error"), [
    (404, fetcher.SourceGoneError),
    (410, fetcher.SourceGoneError),
    (403, fetcher.AccessDeniedError),
    (429, fetcher.NetworkError),
    (500, fetcher.NetworkError),
    (502, fetcher.NetworkError),
    (503, fetcher.NetworkError),
])
async def test_only_a_definitive_base_page_answer_means_the_source_is_gone(monkeypatch, status, error):
    """A background revalidation deletes the cached entry on SourceGoneError and
    AccessDeniedError, so a throttle or an outage must never map to either."""
    transport = httpx.MockTransport(lambda r: httpx.Response(status))
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(fetcher, "_get_sheets_client", lambda: client)
    with pytest.raises(error):
        await fetcher.async_fetch_and_parse(
            "https://docs.google.com/spreadsheets/d/SHEETABC/htmlview", use_cache=False
        )
    await client.aclose()


SHEET = "https://docs.google.com/spreadsheets/d/SHEETABC/htmlview"
SIGN_IN = "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fdocs.google.com%2F"


def _signed_out_client() -> httpx.AsyncClient:
    """The shape Google gives a private sheet: a redirect to a 200 sign-in page."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.google.com":
            return httpx.Response(200, html="<html><body>Sign in</body></html>")
        return httpx.Response(302, headers={"location": SIGN_IN})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


async def test_get_capped_reports_where_the_redirect_chain_ended():
    async with _signed_out_client() as client:
        r = await fetcher._get_capped(client, SHEET)
    assert r.status_code == 200
    assert r.url.host == "accounts.google.com"


@pytest.mark.parametrize("fetch", ["async_fetch_and_parse", "async_fetch_sheet_html"])
async def test_a_private_google_sheet_is_access_denied(monkeypatch, fetch):
    """Google answers a private sheet with a redirect to the sign-in page, which
    comes back as an ordinary 200 with no table. Left unmapped it parsed as
    NoTablesError, which a background revalidation treats as transient."""
    client = _signed_out_client()
    monkeypatch.setattr(fetcher, "_get_sheets_client", lambda: client)
    fetch_fn = getattr(fetcher, fetch)
    with pytest.raises(fetcher.AccessDeniedError):
        await fetch_fn(SHEET, use_cache=False)
    await client.aclose()


@pytest.mark.parametrize("fetch", ["async_fetch_and_parse", "async_fetch_sheet_html"])
async def test_a_sign_in_redirect_from_a_mirror_is_not_access_denied(monkeypatch, fetch):
    from src.config import register_tracker_hosts

    register_tracker_hosts(["https://mirror.example/"])
    client = _signed_out_client()
    monkeypatch.setattr(fetcher, "_get_sheets_client", lambda: client)
    # NoTablesError: the fetch ran and found nothing, rather than being refused up front.
    fetch_fn = getattr(fetcher, fetch)
    with pytest.raises(fetcher.NoTablesError):
        await fetch_fn("https://mirror.example/tracker", use_cache=False)
    await client.aclose()


def test_a_disallowed_host_is_not_a_gone_source():
    assert not issubclass(fetcher.InvalidURLError, fetcher.SourceGoneError)


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
