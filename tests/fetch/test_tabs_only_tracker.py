"""A workbook whose main tab has no songs but whose Misc tab has entries is a real tracker.

Runs the whole fetch pipeline over a synthetic workbook, so the tabs come from the real
secondary-tab loader and not from a hand-built Artist.
"""

from __future__ import annotations

from src.fetcher import async_fetch_and_parse, get_cached_parsed_bytes
from tests.conftest import read_synthetic

URL = "https://docs.google.com/spreadsheets/d/TABSONLY/htmlview"
EMPTY_MAIN = "<html><body><table><tbody><tr><td>Nothing here yet</td></tr></tbody></table></body></html>"
NAMES = {"100": "Unreleased", "200": "Misc"}


def _client(workbook_client, *, fail=None):
    return workbook_client({"100": EMPTY_MAIN, "200": read_synthetic("misc_tab")},
                           tab_names=NAMES, fail_gids=fail)


async def test_misc_only_workbook_keeps_its_tab_entries_and_is_cached(
    workbook_client, patch_sheets_client, monkeypatch
):
    monkeypatch.delenv("LEAKSHEET_GOOGLE_API_KEY", raising=False)
    patch_sheets_client(_client(workbook_client))
    artist = await async_fetch_and_parse(URL, use_cache=False, write_cache=True)
    assert artist.total_versions == 0
    assert sum(len(t.entries) for t in artist.tabs) > 0
    assert get_cached_parsed_bytes(URL) is not None


def test_failed_tabs_keep_a_songless_parse_out_of_the_cache():
    """A misc tab that loaded cannot vouch for song tabs that did not."""
    from src.fetcher import _collapse_reason

    assert _collapse_reason("k", 0, 0, 0, tab_entries=3) is None
    assert _collapse_reason("k", 0, 0, 1, tab_entries=3) is not None
