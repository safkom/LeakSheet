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
from src.config import (
    register_tracker_hosts,
    reset_tracker_hosts,
    sheet_host_allowed,
    tracker_hosts_are_stale,
)
from src.fetcher import InvalidURLError, _assert_sheet_host_allowed


@pytest.fixture(autouse=True)
def _clean_hosts(monkeypatch):
    monkeypatch.delenv("LEAKSHEET_EXTRA_SHEET_HOSTS", raising=False)
    reset_tracker_hosts()
    yield
    reset_tracker_hosts()


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

    async def test_miss_triggers_one_refresh_then_succeeds(self, monkeypatch):
        calls = []

        async def _refresh():
            calls.append(1)
            register_tracker_hosts(["https://fresh.example/x"])

        monkeypatch.setattr(fetcher, "_refresh_tracker_hosts", _refresh)
        await _assert_sheet_host_allowed("https://fresh.example/sheet")
        assert calls == [1]

        # Second miss inside the throttle window must not refetch the feed —
        # otherwise a flood of bogus hosts becomes an amplifier.
        with pytest.raises(InvalidURLError):
            await _assert_sheet_host_allowed("https://still-unknown.example/x")
        assert calls == [1]

    async def test_refresh_failure_does_not_hot_loop(self, monkeypatch):
        async def _boom():
            raise RuntimeError("feed down")

        monkeypatch.setattr(fetcher, "_refresh_tracker_hosts", _boom)
        with pytest.raises(RuntimeError):
            await _assert_sheet_host_allowed("https://unknown.example/x")


class TestSheetsClientTransport:
    def test_sheets_client_uses_the_public_only_transport(self):
        from src.streaming import PublicOnlyAsyncTransport

        fetcher._sheets_client = None
        client = fetcher._get_sheets_client()
        try:
            # An allowlisted host must not be able to 30x the fetch into
            # RFC1918 — the guard runs per hop, at connect.
            assert isinstance(client._transport, PublicOnlyAsyncTransport)
            assert client.follow_redirects
        finally:
            fetcher._sheets_client = None


class TestHostHarvesting:
    """Hosts come from the parsed feed rows, not from every href on the page.

    A regex over hrefs also swept up discord.gg, reddit.com and gstatic.com
    from the TrackerHub page furniture, quietly widening what the backend
    would fetch.
    """

    FEED = (
        "<table>"
        '<tr><td><a href="https://www.google.com/url?q=https://newone.net/x&amp;sa=D">'
        "⭐ New One</a></td><td>by someone</td><td>Yes</td><td>Yes</td></tr>"
        '<tr><td><a href="https://discord.gg/invite">Join our Discord</a></td>'
        "<td></td><td></td><td></td></tr>"
        "</table>"
    )

    def test_only_real_tracker_rows_contribute_hosts(self):
        from src.parser import parse_trackerhub

        register_tracker_hosts([e.url for e in parse_trackerhub(self.FEED)])
        assert sheet_host_allowed("newone.net")
        # Banner row — a link, but no credits and no status flags.
        assert not sheet_host_allowed("discord.gg")
