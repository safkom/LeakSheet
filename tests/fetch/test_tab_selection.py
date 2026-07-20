"""End-to-end tab selection through the REAL async fetch pipeline, offline.

Drives ``async_fetch_and_parse`` against a synthetic multi-tab workbook served
by ``httpx.MockTransport`` (injected via ``_get_sheets_client``). This is the
coverage the suite was missing: everything between "here is a URL" and
``parse_sheet`` — base-page fetch, GID discovery, tab prioritization, the
misc-tab-GID guard, misc-entry merge, and Art-tab image application — none of
which the parse-only harnesses touched.

All tests pass ``use_cache=False, write_cache=False`` so no run reads or writes
the (already tmp-isolated) file cache.
"""

from __future__ import annotations

import pytest

from src.fetcher import async_fetch_and_parse
from tests.conftest import read_synthetic

URL = "https://docs.google.com/spreadsheets/d/SYNTH123/htmlview"

# gid → tab HTML for the full synthetic workbook.
WORKBOOK = {
    "100": read_synthetic("main_tab"),
    "200": read_synthetic("misc_tab"),
    "300": read_synthetic("art_tab"),
    "400": read_synthetic("recent_tab"),
}
TAB_NAMES = {"100": "Unreleased", "200": "Misc", "300": "Art", "400": "Recent"}


async def _fetch(client, patch_sheets_client, **kwargs):
    patch_sheets_client(client)
    return await async_fetch_and_parse(URL, use_cache=False, write_cache=False, **kwargs)


class TestPrimaryTabSelection:
    async def test_selects_unreleased_and_merges_secondary_tabs(
        self, workbook_client, patch_sheets_client
    ):
        client = workbook_client(WORKBOOK, tab_names=TAB_NAMES)
        artist = await _fetch(client, patch_sheets_client)

        # Main "Unreleased" tab won — not the small "Recent" landing tab.
        assert [e.name for e in artist.eras] == ["Debut Era", "Sophomore Era"]
        assert artist.total_songs == 4

        # Art tab applied high-quality era images.
        assert artist.eras[0].art_url == "https://lh3.googleusercontent.com/debut-hq"
        assert artist.eras[1].art_url == "https://lh3.googleusercontent.com/soph-hq"

        # Misc tab merged into misc_entries, kept out of the era tree.
        assert [m.name for m in artist.misc_entries] == ["Music Video One", "Interview Clip"]
        assert {m.source_tab for m in artist.misc_entries} == {"misc"}

    async def test_unreleased_wins_even_when_not_first_discovered(
        self, workbook_client, patch_sheets_client
    ):
        # Put Recent ahead of Unreleased in discovery order; prioritization must
        # still move the Unreleased tab to the front.
        names = {"400": "Recent", "100": "Unreleased", "200": "Misc"}
        client = workbook_client(
            {"400": WORKBOOK["400"], "100": WORKBOOK["100"], "200": WORKBOOK["200"]},
            tab_names=names,
        )
        artist = await _fetch(client, patch_sheets_client)
        assert [e.name for e in artist.eras] == ["Debut Era", "Sophomore Era"]

    async def test_no_unreleased_tab_picks_most_eras(
        self, workbook_client, patch_sheets_client
    ):
        # Neither tab is named like the unreleased/main tab → the one with the
        # most eras (the real tracker) must win over the 1-era Recent tab.
        names = {"100": "Songs", "400": "Recent"}
        client = workbook_client(
            {"100": WORKBOOK["100"], "400": WORKBOOK["400"]}, tab_names=names
        )
        artist = await _fetch(client, patch_sheets_client)
        assert artist.total_songs == 4
        assert "Recently Added" not in [e.name for e in artist.eras]


class TestMiscTabGidRegression:
    """A URL pointing straight at the Misc tab's GID must NOT be parsed as the
    main sheet — parse_sheet can extract a plausible-but-wrong era list from the
    misc grammar. The fetcher must recognize the GID as a misc tab and fall
    through to full discovery. (This is the bug tests/fetch/test_gid_misc_tab.py
    documents at the unit level; here it's verified end-to-end.)"""

    async def test_requested_misc_gid_falls_through_to_main(
        self, workbook_client, patch_sheets_client
    ):
        client = workbook_client(WORKBOOK, tab_names=TAB_NAMES)
        artist = await _fetch(client, patch_sheets_client, gid="200")  # 200 == Misc
        # Real main tab parsed, not garbage from the misc tab.
        assert [e.name for e in artist.eras] == ["Debut Era", "Sophomore Era"]
        assert artist.total_songs == 4
        # And the misc tab is still consumed as misc entries, not lost.
        assert len(artist.misc_entries) == 2

    async def test_requested_main_gid_short_circuits(
        self, workbook_client, patch_sheets_client
    ):
        # A direct link to the main tab's GID returns it immediately (and still
        # discovers/merges the secondary tabs).
        client = workbook_client(WORKBOOK, tab_names=TAB_NAMES)
        artist = await _fetch(client, patch_sheets_client, gid="100")
        assert [e.name for e in artist.eras] == ["Debut Era", "Sophomore Era"]


class TestSourceUrlAndResilience:
    async def test_source_url_is_the_original(self, workbook_client, patch_sheets_client):
        client = workbook_client(WORKBOOK, tab_names=TAB_NAMES)
        artist = await _fetch(client, patch_sheets_client)
        assert artist.source_url == URL

    async def test_failing_secondary_tab_does_not_break_request(
        self, workbook_client, patch_sheets_client
    ):
        # Art tab (gid 300) 503s — the request must still succeed with the main
        # eras and misc entries; art just isn't upgraded.
        client = workbook_client(WORKBOOK, tab_names=TAB_NAMES, fail_gids={"300"})
        artist = await _fetch(client, patch_sheets_client)
        assert artist.total_songs == 4
        assert len(artist.misc_entries) == 2
