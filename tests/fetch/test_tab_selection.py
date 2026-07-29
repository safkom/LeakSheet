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


class TestHubWorkbook:
    """A workbook whose main tab is a hub of category descriptions, with the
    catalogue split across unclassified sibling tabs (Avicii, 2026-07-27).

    Two things had to hold: the song-less hub must not win selection, and the
    sibling tabs must be merged in. Before both, Avicii returned 0 songs.
    """

    HUB_WORKBOOK = {
        "100": read_synthetic("hub_tab"),        # "Main" — eras, no songs
        "500": read_synthetic("catalogue_tab"),  # unclassified, has songs
        "400": read_synthetic("recent_tab"),     # deliberately excluded
    }
    HUB_NAMES = {"100": "Main", "500": "Rare & Lost", "400": "Recent"}

    async def test_song_less_hub_never_wins_selection(
        self, workbook_client, patch_sheets_client
    ):
        client = workbook_client(self.HUB_WORKBOOK, tab_names=self.HUB_NAMES)
        artist = await _fetch(client, patch_sheets_client)
        # "Catalogue Index" is the hub's own era — it must not be the answer.
        assert artist.total_songs > 0
        assert [e.name for e in artist.eras][0] != "Catalogue Index"

    async def test_sibling_catalogue_tabs_are_merged(
        self, workbook_client, patch_sheets_client
    ):
        workbook = dict(self.HUB_WORKBOOK)
        workbook["600"] = read_synthetic("main_tab")
        names = dict(self.HUB_NAMES, **{"600": "Leaks"})
        client = workbook_client(workbook, tab_names=names)
        artist = await _fetch(client, patch_sheets_client)

        eras = {e.name: e for e in artist.eras}
        # main_tab's 4 songs + catalogue_tab's 3.
        assert artist.total_songs == 7
        # Existing era gains a section named after the sibling tab.
        debut_sections = {s.name: len(s.songs) for s in eras["Debut Era"].sections}
        assert debut_sections.get("Rare & Lost") == 1
        # New era is appended whole, with no synthetic section header.
        assert "Rarities" in eras
        assert [s.name for s in eras["Rarities"].sections] == [""]

    async def test_excluded_tabs_are_not_aggregated(
        self, workbook_client, patch_sheets_client
    ):
        workbook = dict(self.HUB_WORKBOOK)
        workbook["600"] = read_synthetic("main_tab")
        names = dict(self.HUB_NAMES, **{"600": "Leaks"})
        client = workbook_client(workbook, tab_names=names)
        artist = await _fetch(client, patch_sheets_client)
        # gid 400 is "Recent" — a duplicate view, never extra catalogue.
        assert "Recently Added" not in [e.name for e in artist.eras]

    async def test_healthy_workbook_skips_aggregation(
        self, workbook_client, patch_sheets_client
    ):
        # No hub → the unclassified "Rare & Lost" tab is left alone, so a
        # normal tracker never pays for the extra fetches.
        workbook = {"100": read_synthetic("main_tab"), "500": read_synthetic("catalogue_tab")}
        client = workbook_client(workbook, tab_names={"100": "Unreleased", "500": "Rare & Lost"})
        artist = await _fetch(client, patch_sheets_client)
        assert artist.total_songs == 4
        assert "Rarities" not in [e.name for e in artist.eras]

    async def test_failing_sibling_tab_does_not_break_request(
        self, workbook_client, patch_sheets_client
    ):
        workbook = dict(self.HUB_WORKBOOK)
        workbook["600"] = read_synthetic("main_tab")
        names = dict(self.HUB_NAMES, **{"600": "Leaks"})
        client = workbook_client(workbook, tab_names=names, fail_gids={"500"})
        artist = await _fetch(client, patch_sheets_client)
        assert artist.total_songs == 4  # main tab only, request still succeeds


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


class TestHubWorkbookAccounting:
    """The merged artist's parse_metadata must describe the WHOLE artist.

    parse_metadata is what makes silent data loss measurable (the identity
    total == song + skipped + footer + other). Left describing only the
    winning tab, it would under-report every hub workbook — and the
    skipped-ratio health check reads it.
    """

    async def test_row_accounting_covers_merged_tabs(
        self, workbook_client, patch_sheets_client
    ):
        workbook = {
            "100": read_synthetic("hub_tab"),
            "500": read_synthetic("catalogue_tab"),
            "600": read_synthetic("main_tab"),
        }
        names = {"100": "Main", "500": "Rare & Lost", "600": "Leaks"}
        artist = await _fetch(
            workbook_client(workbook, tab_names=names), patch_sheets_client
        )
        md = artist.parse_metadata
        assert md is not None
        # Identity holds across the merge.
        assert md.total_rows == (
            md.song_rows + md.skipped_rows + md.footer_rows + md.other_rows
        )
        # And it counts the sibling's rows, not just the winner's.
        assert md.song_rows == artist.total_versions

    def test_hub_tab_is_not_re_fetched_as_a_candidate(self):
        from src import fetcher

        names = {"100": "Main", "500": "Rare & Lost", "600": "Leaks"}
        cands = fetcher._hub_workbook_candidates(names, {"600", "100", None})
        assert [g for g, _ in cands] == ["500"]


class TestHubDuplicateGuard:
    async def test_mystery_titled_tab_is_not_read_as_a_duplicate(
        self, workbook_client, patch_sheets_client, tmp_path
    ):
        """A sibling tab of unidentifiable titles must still merge.

        "???" and "??" both normalise to the empty key, so comparing raw key
        sets made a whole tab of mystery tracks look like one big duplicate of
        any main tab that had a single "???" row.
        """
        mystery = (
            "<html><body><table>"
            "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Available</td>"
            "<td>Quality</td><td>Link(s)</td></tr>"
            "<tr><td>2 Full</td><td>Vault</td><td></td><td></td><td></td><td></td></tr>"
            "<tr><td>Vault</td><td>???</td><td></td><td>Full</td><td>High Quality</td>"
            "<td><a href='https://pillows.su/f/m1'>a</a></td></tr>"
            "<tr><td>Vault</td><td>??</td><td></td><td>Full</td><td>High Quality</td>"
            "<td><a href='https://pillows.su/f/m2'>b</a></td></tr>"
            "</table></body></html>"
        )
        main_with_placeholder = read_synthetic("main_tab").replace(
            "<td>Debut Era</td><td>⭐ Sunrise</td>", "<td>Debut Era</td><td>???</td>", 1
        )
        workbook = {
            "100": read_synthetic("hub_tab"),
            "600": main_with_placeholder,
            "700": mystery,
        }
        names = {"100": "Main", "600": "Leaks", "700": "Vault Tapes"}
        artist = await _fetch(
            workbook_client(workbook, tab_names=names), patch_sheets_client
        )
        assert "Vault" in [e.name for e in artist.eras]


class TestHubSectionIdentity:
    def test_same_named_tabs_reuse_one_section(self):
        """Two siblings merging into one era must not create two sections
        with the same name — the iOS row id is era+group+name, so a duplicate
        silently drops rows from the list."""
        from src.fetcher import _merge_aggregated_eras
        from src.models import Artist, Era, Section, Song, SongVersion

        def artist_with(era_name, *songs):
            return Artist(name="T", slug="t", eras=[Era(name=era_name, sections=[
                Section(songs=[
                    Song(base_name=n, versions=[SongVersion(name=n)]) for n in songs
                ])
            ])])

        target = artist_with("Debut Era", "One")
        _merge_aggregated_eras(target, "Extras", artist_with("Debut Era", "Two"))
        _merge_aggregated_eras(target, "Extras", artist_with("Debut Era", "Three"))

        named = [s for s in target.eras[0].sections if s.name == "Extras"]
        assert len(named) == 1
        assert [s.base_name for s in named[0].songs] == ["Two", "Three"]
