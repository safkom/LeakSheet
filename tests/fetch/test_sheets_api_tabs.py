"""Content tabs read through the Sheets API v4, end to end and offline.

With LEAKSHEET_GOOGLE_API_KEY set, a docs.google.com workbook's content tabs
(Misc, Grails / Wanted, …) come from one spreadsheets.get call instead of one
htmlview page each; the main and Art tabs stay on htmlview for their images.
The output must equal the htmlview-only parse, and any API failure must fall
back to htmlview.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

import httpx
import pytest

from src.fetcher import async_fetch_and_parse
from src.parser import _clean_link, extract_table
from tests.conftest import make_workbook_handler, read_synthetic

URL = "https://docs.google.com/spreadsheets/d/SYNTH123/htmlview"
KEY = "test-key-not-real"
WORKBOOK = {
    "100": read_synthetic("main_tab"),
    "200": read_synthetic("misc_tab"),
    "300": read_synthetic("art_tab"),
    "500": read_synthetic("grails_wanted_tab"),
}
TAB_NAMES = {"100": "Unreleased", "200": "Misc", "300": "Art", "500": "Grails / Wanted"}
CONTENT_GIDS = {"200", "500"}


def _api_sheet(gid: str) -> dict:
    """The API's view of a synthetic tab: same cells, links as whole-cell hyperlinks."""
    rows = extract_table(WORKBOOK[gid])
    values = []
    for row in rows:
        cells = []
        for cell in row:
            assert len(cell.links) <= 1, "fixture cells carry one link at most"
            value = {"formattedValue": cell.text} if cell.text else {}
            if cell.links:
                value["hyperlink"] = _clean_link(cell.links[0])
            cells.append(value)
        values.append({"values": cells})
    return {
        "properties": {
            "sheetId": int(gid), "title": TAB_NAMES[gid],
            "gridProperties": {"rowCount": len(rows), "columnCount": max(map(len, rows))},
        },
        "data": [{"rowData": values}],
    }


class Recorder:
    """A mock transport serving both htmlview and the API; records every request."""

    def __init__(self, api=None, fail_gids=None):
        self.requests: list[httpx.Request] = []
        self._htmlview = make_workbook_handler(WORKBOOK, tab_names=TAB_NAMES, fail_gids=fail_gids)
        self._api = api or self.ok

    @staticmethod
    def ok(request: httpx.Request) -> httpx.Response:
        titles = [unquote(r).strip("'") for r in request.url.params.get_list("ranges")]
        sheets = [_api_sheet(g) for g, name in TAB_NAMES.items() if name in titles]
        return httpx.Response(200, json={"sheets": sheets})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "sheets.googleapis.com":
            return self._api(request)
        return self._htmlview.handle_request(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), follow_redirects=True)

    def api_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == "sheets.googleapis.com"]

    def htmlview_gids(self) -> set[str]:
        return {g for r in self.requests if (g := r.url.params.get("gid"))}


async def _parse(recorder, patch_sheets_client, url=URL, timer=None):
    patch_sheets_client(recorder.client())
    artist = await async_fetch_and_parse(url, use_cache=False, write_cache=False, timer=timer)
    return json.loads(artist.model_dump_json())


@pytest.fixture
async def htmlview_only(patch_sheets_client):
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("LEAKSHEET_GOOGLE_API_KEY", raising=False)
        return await _parse(Recorder(), patch_sheets_client)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("LEAKSHEET_GOOGLE_API_KEY", KEY)


class TestApiTabs:
    async def test_content_tabs_come_from_one_api_call(self, with_key, htmlview_only, patch_sheets_client):
        rec = Recorder()
        out = await _parse(rec, patch_sheets_client)
        assert len(rec.api_requests()) == 1
        assert not rec.htmlview_gids() & CONTENT_GIDS
        assert {"100", "300"} <= rec.htmlview_gids()  # main and Art keep their images
        assert out == htmlview_only
        assert out["tabs"] or out["misc_entries"]

    async def test_the_key_travels_only_in_a_header(self, with_key, patch_sheets_client):
        rec = Recorder()
        await _parse(rec, patch_sheets_client)
        (req,) = rec.api_requests()
        assert req.headers["X-Goog-Api-Key"] == KEY
        assert KEY not in str(req.url)
        assert "gzip" in req.headers["User-Agent"]  # Google APIs only compress for such agents
        assert sorted(req.url.params.get_list("ranges")) == ["'Grails / Wanted'", "'Misc'"]

    async def test_no_key_means_no_api_call(self, monkeypatch, htmlview_only, patch_sheets_client):
        monkeypatch.delenv("LEAKSHEET_GOOGLE_API_KEY", raising=False)
        rec = Recorder()
        assert await _parse(rec, patch_sheets_client) == htmlview_only
        assert rec.api_requests() == []

    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_an_empty_key_means_no_api_call(self, monkeypatch, blank, htmlview_only, patch_sheets_client):
        # deploy.sh exports every named variable, so an unset key arrives as "".
        monkeypatch.setenv("LEAKSHEET_GOOGLE_API_KEY", blank)
        rec = Recorder()
        assert await _parse(rec, patch_sheets_client) == htmlview_only
        assert rec.api_requests() == []

    async def test_mirror_hosts_never_call_the_api(self, with_key, patch_sheets_client):
        rec = Recorder()
        await _parse(rec, patch_sheets_client, url="https://yetracker.net/")
        assert rec.api_requests() == []


class TestFallback:
    async def test_429_falls_back_to_htmlview_and_backs_off(self, with_key, htmlview_only, patch_sheets_client):
        rec = Recorder(api=lambda r: httpx.Response(429, headers={"Retry-After": "120"}, json={"error": {}}))
        assert await _parse(rec, patch_sheets_client) == htmlview_only
        assert CONTENT_GIDS <= rec.htmlview_gids()
        again = Recorder()
        assert await _parse(again, patch_sheets_client) == htmlview_only
        assert again.api_requests() == []  # inside the backoff window

    async def test_a_429_on_the_title_lookup_backs_off(self, with_key, htmlview_only, patch_sheets_client):
        def api(request: httpx.Request) -> httpx.Response:
            if "includeGridData" in request.url.params:
                return httpx.Response(400, json={"error": {"message": "Unable to parse range"}})
            return httpx.Response(429, headers={"Retry-After": "120"}, json={"error": {}})

        assert await _parse(Recorder(api=api), patch_sheets_client) == htmlview_only
        again = Recorder()
        assert await _parse(again, patch_sheets_client) == htmlview_only
        assert again.api_requests() == []  # the quota is still spent: no call inside the window

    async def test_a_key_the_title_lookup_rejects_is_not_retried_on_every_parse(
        self, with_key, htmlview_only, patch_sheets_client
    ):
        def api(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"message": "API key not valid"}})

        assert await _parse(Recorder(api=api), patch_sheets_client) == htmlview_only
        again = Recorder(api=api)
        assert await _parse(again, patch_sheets_client) == htmlview_only
        assert again.api_requests() == []  # one bad key must not cost two calls per parse

    async def test_any_other_error_falls_back(self, with_key, htmlview_only, patch_sheets_client):
        rec = Recorder(api=lambda r: httpx.Response(400, json={"error": {"message": "Unable to parse range"}}))
        assert await _parse(rec, patch_sheets_client) == htmlview_only
        assert CONTENT_GIDS <= rec.htmlview_gids()

    async def test_a_redirect_is_not_followed(self, with_key, htmlview_only, patch_sheets_client):
        rec = Recorder(api=lambda r: httpx.Response(302, headers={"Location": "https://elsewhere.example/x"}))
        assert await _parse(rec, patch_sheets_client) == htmlview_only
        assert all(r.url.host != "elsewhere.example" for r in rec.requests)

    async def test_a_tab_missing_from_the_response_is_read_from_htmlview(
        self, with_key, htmlview_only, patch_sheets_client
    ):
        rec = Recorder(api=lambda r: httpx.Response(200, json={"sheets": [_api_sheet("200")]}))
        assert await _parse(rec, patch_sheets_client) == htmlview_only
        assert "500" in rec.htmlview_gids() and "200" not in rec.htmlview_gids()

    async def test_titles_htmlview_trims_are_looked_up_by_sheet_id(self, with_key, htmlview_only, patch_sheets_client):
        # The tab listing strips names, so a title with edge spaces is not a valid range.
        exact = {"200": " Misc", "500": "Grails / Wanted "}

        def api(request: httpx.Request) -> httpx.Response:
            if "includeGridData" not in request.url.params:
                return httpx.Response(200, json={"sheets": [
                    {"properties": {"sheetId": int(g), "title": exact.get(g, n)}} for g, n in TAB_NAMES.items()]})
            ranges = request.url.params.get_list("ranges")
            if any(unquote(r)[1:-1] not in exact.values() for r in ranges):
                return httpx.Response(400, json={"error": {"message": "Unable to parse range"}})
            return Recorder.ok(httpx.Request("GET", "https://x/?" + "&".join(
                f"ranges='{TAB_NAMES[g]}'" for g, t in exact.items() if f"'{t}'" in ranges)))

        rec = Recorder(api=api)
        assert await _parse(rec, patch_sheets_client) == htmlview_only
        assert len(rec.api_requests()) == 3
        assert not rec.htmlview_gids() & CONTENT_GIDS

    async def test_gid_urls_read_content_tabs_from_the_api_too(self, monkeypatch, patch_sheets_client):
        expected = await _parse(Recorder(), patch_sheets_client, url=URL + "#gid=100")
        monkeypatch.setenv("LEAKSHEET_GOOGLE_API_KEY", KEY)
        rec = Recorder()
        assert await _parse(rec, patch_sheets_client, url=URL + "#gid=100") == expected
        assert len(rec.api_requests()) == 1
        assert not rec.htmlview_gids() & CONTENT_GIDS


class TestFailedTabs:
    """The failed_tabs count (docs/decisions.md::fetcher.py::cache-collapse-guard) covers API tabs."""

    async def test_tabs_read_through_the_api_are_counted_as_loaded(self, with_key, patch_sheets_client):
        from src.fetcher import PhaseTimer

        timer = PhaseTimer()
        await _parse(Recorder(), patch_sheets_client, timer=timer)
        # Main and Art over htmlview, Misc and Grails / Wanted over the API.
        assert timer.tab_counts() == (0, 4)

    async def test_a_tab_the_api_lacks_and_htmlview_fails_is_a_failed_tab(self, with_key, patch_sheets_client):
        from src.fetcher import PhaseTimer

        timer = PhaseTimer()
        rec = Recorder(api=lambda r: httpx.Response(200, json={"sheets": [_api_sheet("200")]}), fail_gids={"500"})
        await _parse(rec, patch_sheets_client, timer=timer)
        assert timer.tab_counts() == (1, 4)

    async def test_a_failed_api_call_leaves_the_htmlview_accounting_alone(self, with_key, patch_sheets_client):
        from src.fetcher import PhaseTimer

        timer = PhaseTimer()
        rec = Recorder(api=lambda r: httpx.Response(429), fail_gids={"500"})
        await _parse(rec, patch_sheets_client, timer=timer)
        assert timer.tab_counts() == (1, 4)

