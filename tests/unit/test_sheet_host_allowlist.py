"""The /sheet host allowlist.

POST /sheet takes a URL from the caller and fetches it server-side. Without a
host check the backend is an SSRF sink: cloud metadata (169.254.169.254) and
RFC1918 hosts are reachable, any internal page holding a <table> comes back
parsed, and the distinct 400/404/502 mappings make it an internal port
scanner. The stream and image paths were hardened in the 2026-07-21 pass;
/sheet never was.
"""

import pytest

from src import fetcher
from src import config
from src.config import (
    register_tracker_hosts,
    sheet_host_allowed,
    tracker_hosts_are_stale,
)
from src.fetcher import InvalidURLError, _assert_sheet_host_allowed


@pytest.fixture(autouse=True)
def _clean_hosts(monkeypatch):
    monkeypatch.delenv("LEAKSHEET_EXTRA_SHEET_HOSTS", raising=False)
    monkeypatch.setattr(config, "_tracker_hosts", set())
    monkeypatch.setattr(config, "_tracker_hosts_at", 0.0)


class TestAllowlistMembership:
    def test_seeded_hosts_allowed(self):
        assert sheet_host_allowed("docs.google.com")
        assert sheet_host_allowed("yetracker.net")

    def test_host_match_is_case_insensitive(self):
        assert sheet_host_allowed("DOCS.GOOGLE.COM")

    def test_unknown_host_rejected(self):
        assert not sheet_host_allowed("evil.example")
        assert not sheet_host_allowed("169.254.169.254")
        assert not sheet_host_allowed(None)

    def test_subdomains_are_not_implicitly_allowed(self):
        # Exact-match only: an attacker-controlled *.google.com subdomain is
        # not a tracker host.
        assert not sheet_host_allowed("evil.docs.google.com")

    def test_env_escape_hatch(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_EXTRA_SHEET_HOSTS", "sheets.example, other.example")
        assert sheet_host_allowed("sheets.example")
        assert sheet_host_allowed("other.example")
        assert not sheet_host_allowed("third.example")

    def test_trackerhub_urls_register_their_hosts(self):
        assert not sheet_host_allowed("newtracker.net")
        register_tracker_hosts([
            "https://newtracker.net/sheet",
            "https://docs.google.com/spreadsheets/d/ABC/edit",
            "not a url",
        ])
        assert sheet_host_allowed("newtracker.net")

    def test_registering_stamps_the_refresh_clock(self):
        assert tracker_hosts_are_stale()
        register_tracker_hosts([])
        assert not tracker_hosts_are_stale()


class TestFetcherGuard:
    async def test_metadata_endpoint_rejected(self, monkeypatch):
        # Stale hosts would normally trigger one TrackerHub refresh; make it a
        # no-op so this asserts the rejection, not the network.
        async def _noop():
            register_tracker_hosts([])
        monkeypatch.setattr(fetcher, "_refresh_tracker_hosts", _noop)
        with pytest.raises(InvalidURLError, match="host not allowed"):
            await _assert_sheet_host_allowed("http://169.254.169.254/latest/meta-data/")

    async def test_allowed_host_passes(self):
        await _assert_sheet_host_allowed("https://docs.google.com/spreadsheets/d/X/htmlview")

    async def test_miss_triggers_a_refresh_then_succeeds(self, monkeypatch):
        calls = []

        async def _refresh():
            calls.append(1)
            register_tracker_hosts(["https://fresh.example/x"])

        monkeypatch.setattr(fetcher, "_refresh_tracker_hosts", _refresh)
        await _assert_sheet_host_allowed("https://fresh.example/sheet")
        assert calls == [1]

    async def test_refresh_self_throttles(self, monkeypatch):
        # A flood of bogus hosts must not become a flood of feed fetches, so
        # the throttle lives inside the refresh rather than at its call site.
        fetches = []

        def _client():
            fetches.append(1)
            raise AssertionError("should not be reached inside the window")

        register_tracker_hosts([])  # stamps the clock -> not stale
        monkeypatch.setattr(fetcher, "_get_sheets_client", _client)
        await fetcher._refresh_tracker_hosts()
        assert fetches == []

    async def test_refresh_failure_does_not_hot_loop(self, monkeypatch):
        async def _boom():
            raise RuntimeError("feed down")

        monkeypatch.setattr(fetcher, "_refresh_tracker_hosts", _boom)
        with pytest.raises(RuntimeError):
            await _assert_sheet_host_allowed("https://unknown.example/x")


class TestSheetsClientTransport:
    def test_sheets_client_uses_the_public_only_transport(self, monkeypatch):
        from src.streaming import PublicOnlyAsyncTransport

        monkeypatch.setattr(fetcher, "_sheets_client", None)
        client = fetcher._get_sheets_client()
        # An allowlisted host must not be able to 30x the fetch into
        # RFC1918 — the guard runs per hop, at connect.
        assert isinstance(client._transport, PublicOnlyAsyncTransport)
        assert client.follow_redirects


class TestHostHarvesting:
    """Hosts come from the parsed feed rows, not from anything else on the page.

    A regex over hrefs once swept discord.gg, reddit.com and gstatic.com out of
    the old TrackerHub page furniture, quietly widening what the backend would
    fetch. The ArtistGrid CSV has no furniture, but the same rule holds: only a
    row's url field contributes, and a bare sheet id maps to docs.google.com
    rather than being read as a host.
    """

    FEED = (
        "name,url,credit,links_work,updated,best\n"
        "New One,newone.net,someone,1,1,true\n"
        "Sheet Artist,1AbCdEfGhIjK,crew,1,1,false\n"
        ",nameless.net,ghost,1,1,false\n"
    )

    def test_only_real_tracker_rows_contribute_hosts(self):
        from src.parser import parse_artistgrid_csv

        register_tracker_hosts([e.url for e in parse_artistgrid_csv(self.FEED)])
        assert sheet_host_allowed("newone.net")
        assert sheet_host_allowed("docs.google.com")
        assert not sheet_host_allowed("1abcdefghijk")
        # A row with no name is dropped, so its host never registers.
        assert not sheet_host_allowed("nameless.net")


class TestSubPageGuard:
    """The allowlist has to hold for every tab, not just the URL we were given.

    A workbook's tab URLs come out of the page's own JavaScript
    (``_discover_page_urls``), so an absolute entry there is written by whoever
    controls the sheet. The base URL is checked once, up front; before this
    guard a sub-page could send the fetcher at any public host and have the
    response parsed and written to the disk cache.
    """

    BASE = "https://docs.google.com/spreadsheets/d/SHEET/htmlview"

    def test_off_allowlist_absolute_tab_url_is_ignored(self):
        url = fetcher._build_sheet_html_url(
            self.BASE, "42", {"42": "https://evil.example/1.html"}
        )
        assert "evil.example" not in url
        # Falls through to the query form, which is same-host by construction.
        assert url.startswith("https://docs.google.com/")
        assert "gid=42" in url

    def test_allowlisted_absolute_tab_url_is_used(self):
        # Not a seed host, so this proves registration is what admits it.
        register_tracker_hosts(["https://feedonly-tracker.example/"])
        url = fetcher._build_sheet_html_url(
            self.BASE, "42", {"42": "https://feedonly-tracker.example/7.html"}
        )
        assert url == "https://feedonly-tracker.example/7.html"

    def test_relative_tab_url_stays_on_the_base_host(self):
        url = fetcher._build_sheet_html_url(self.BASE, "42", {"42": "/7.html"})
        assert url == "https://docs.google.com/7.html"


class TestSameSite:
    @pytest.mark.parametrize("host, base", [
        ("x.net", "x.net"),
        ("cdn.x.net", "x.net"),
        ("x.net", "www.x.net"),
        ("CDN.X.NET", "x.net"),
    ])
    def test_same_site(self, host, base):
        assert fetcher._same_site(host, base)

    @pytest.mark.parametrize("host, base", [
        ("evilx.net", "x.net"),        # suffix without a dot boundary
        ("x.net.evil.example", "x.net"),
        ("evil.example", "x.net"),
        (None, "x.net"),
        ("x.net", None),
    ])
    def test_not_same_site(self, host, base):
        assert not fetcher._same_site(host, base)
