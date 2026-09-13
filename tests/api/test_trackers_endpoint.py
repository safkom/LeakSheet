"""Tests for the /trackers ArtistGrid discovery endpoint."""


import pytest
from fastapi.testclient import TestClient

import src.api as api
from src.api import app
from src.parser import _clean_link, parse_artistgrid_csv

REDIRECT = (
    "https://www.google.com/url?q=https://docs.google.com/spreadsheets/d/"
    "1UBHQ067bIEDH3TapHIt3MCdwDNRe30Qv0VdBP9JLgFM/edit?gid%3D1520634709%23gid%3D1520634709"
    "&sa=D&source=editors&ust=1783979670067670&usg=AOvVaw2AtxBitQBaM7ebu87lrfom"
)

class TestUnwrapGoogleRedirect:
    def test_unwraps_q_param(self):
        assert _clean_link(REDIRECT) == (
            "https://docs.google.com/spreadsheets/d/"
            "1UBHQ067bIEDH3TapHIt3MCdwDNRe30Qv0VdBP9JLgFM/edit"
            "?gid=1520634709#gid=1520634709"
        )

    def test_passthrough_direct_url(self):
        url = "https://docs.google.com/spreadsheets/d/ABC/edit"
        assert _clean_link(url) == url

    def test_passthrough_google_non_redirect(self):
        url = "https://www.google.com/search?q=hello"
        assert _clean_link(url) == url


FIXTURE_CSV = """name,url,credit,links_work,updated,best
50 Cent,1UBHQ067bIEDH3TapHIt3MCdwDNRe30Qv0VdBP9JLgFM,G-Man Junior,1,1,true
Deftones,deftonestracker.net,troabroa,1,1,true
Plain Artist,PLAIN,someone,1,0,false
Flagless Artist,NOFLAGS,crew,,,false
"""


class TestParseArtistgridCsv:
    def test_fixture(self):
        entries = parse_artistgrid_csv(FIXTURE_CSV)
        names = [e.name for e in entries]
        assert names == ["50 Cent", "Deftones", "Flagless Artist", "Plain Artist"]

        fifty = entries[0]
        assert fifty.best is True
        assert fifty.url == (
            "https://docs.google.com/spreadsheets/d/"
            "1UBHQ067bIEDH3TapHIt3MCdwDNRe30Qv0VdBP9JLgFM/edit"
        )
        assert fifty.credit == "G-Man Junior"
        assert fifty.up_to_date is True
        assert fifty.working_links is True

        # bare domain (non-Google tracker) passes through instead of being
        # treated as a Sheets file ID — dots are the discriminator.
        deftones = entries[1]
        assert deftones.best is True
        assert deftones.url == "https://deftonestracker.net/"

        # best entries sort first, then alphabetical
        assert [e.best for e in entries] == [True, True, False, False]

        plain = next(e for e in entries if e.name == "Plain Artist")
        assert plain.best is False
        assert plain.up_to_date is False
        assert plain.working_links is True

        flagless = next(e for e in entries if e.name == "Flagless Artist")
        assert flagless.up_to_date is None
        assert flagless.working_links is None

    def test_links_work_tristate_unknown_maps_to_none(self):
        csv_text = "name,url,credit,links_work,updated,best\nX,ID123,c,2,1,false\n"
        entries = parse_artistgrid_csv(csv_text)
        assert entries[0].working_links is None

    def test_empty_csv(self):
        assert parse_artistgrid_csv("name,url,credit,links_work,updated,best\n") == []
        assert parse_artistgrid_csv("") == []


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": "text/csv"}


class FakeClient:
    def __init__(self):
        self.response: FakeResponse | None = FakeResponse(FIXTURE_CSV)
        self.calls = 0

    async def get(self, url, headers=None, **kwargs):
        self.calls += 1
        if self.response is None:
            raise RuntimeError("upstream down")
        return self.response


@pytest.fixture()
def trackers_env(monkeypatch):
    fake = FakeClient()
    import src.fetcher as fetcher
    monkeypatch.setattr(fetcher, "_get_sheets_client", lambda: fake)
    monkeypatch.setattr(api, "_trackers_cache", api.TTLCache(ttl=3600.0, max_entries=1))
    monkeypatch.setattr(api, "_trackers_stale", None)
    return TestClient(app), fake


class TestTrackersEndpoint:
    def test_miss_then_hit(self, trackers_env):
        client, fake = trackers_env
        r = client.get("/trackers")
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "miss"
        data = r.json()
        assert len(data) == 4
        assert data[0]["name"] == "50 Cent"

        r2 = client.get("/trackers")
        assert r2.headers["X-Cache-Status"] == "hit"
        assert fake.calls == 1
        assert r2.json() == data

    def test_stale_fallback_on_upstream_error(self, trackers_env, monkeypatch):
        client, fake = trackers_env
        assert client.get("/trackers").status_code == 200

        # Expire the TTL cache and kill the upstream.
        monkeypatch.setattr(api, "_trackers_cache", api.TTLCache(ttl=3600.0, max_entries=1))
        fake.response = None
        r = client.get("/trackers")
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "stale"
        assert len(r.json()) == 4

    def test_seed_fallback_without_stale(self, trackers_env):
        client, fake = trackers_env
        fake.response = None
        r = client.get("/trackers")
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "seed"
        assert len(r.json()) == len(api.SEED_TRACKERS)

    def test_unparseable_page_falls_back_to_seed(self, trackers_env):
        client, fake = trackers_env
        fake.response = FakeResponse("<html><body>nothing here</body></html>")
        r = client.get("/trackers")
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "seed"
