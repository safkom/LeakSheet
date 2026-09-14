"""Era covers outlive Google's image tokens.

Google's `sheets-images-rt` cover URLs carry a signed token that stops working
within minutes to tens of minutes, while a parse is served for hours and clients
keep it for days. So covers loaded only while the parse was young: in production
Ye and Travis showed none while freshly parsed Kendrick and Baby Keem did.
yetracker.net makes it worse by serving Cloudflare copies up to an hour old, so
its tokens are often dead at parse time already.

The backend now downloads each era cover right after parsing, while the token
still works, and the image proxy serves that copy afterwards.
"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import src.api as api
from src.api import app
from src.models import Artist, Era

TRACKER = "https://yetracker.net/"


def _png(width: int = 400, height: int = 400) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _cover(token: str) -> str:
    return f"https://docs.google.com/sheets-images-rt/{token}=w340-h339"


class _Response:
    def __init__(self, url: str, content: bytes, status: int):
        self.url = url
        self.status_code = status
        self.headers = {"content-type": "image/png" if status == 200 else "text/html"}
        self._content = content

    async def aiter_bytes(self):
        yield self._content

    async def aclose(self):
        pass


class _Google:
    """Serves covers only for tokens still alive; everything else is a 403."""

    def __init__(self):
        self.alive: set[str] = set()
        self.requested: list[str] = []

    def build_request(self, method, url, headers=None):
        return SimpleNamespace(url=url)

    async def send(self, request, stream=False):
        self.requested.append(request.url)
        ok = request.url in self.alive
        return _Response(request.url, _png() if ok else b"", 200 if ok else 403)


@pytest.fixture()
def google(monkeypatch, tmp_path):
    fake = _Google()
    monkeypatch.setattr(api, "_get_proxy_client", lambda: fake)
    monkeypatch.setattr(api, "CACHE_DIR", tmp_path)
    return fake


def _artist(*covers: tuple[str, str]) -> Artist:
    return Artist(name="Ye", slug="ye", eras=[Era(name=n, art_url=u) for n, u in covers])


class TestWarmEraArt:
    def test_a_cover_still_loads_after_its_token_expires(self, google):
        url = _cover("fresh")
        google.alive.add(url)
        asyncio.run(api._warm_era_art(_artist(("Donda", url)), TRACKER))

        google.alive.clear()  # the token dies
        google.requested.clear()
        r = TestClient(app).get("/image-proxy", params={"url": url, "w": 320})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        assert google.requested == []  # served from the copy, not upstream

    def test_a_dead_token_reuses_the_last_good_cover_for_that_era(self, google):
        first = _cover("parse1")
        google.alive.add(first)
        asyncio.run(api._warm_era_art(_artist(("Donda", first)), TRACKER))

        # Next parse: yetracker.net served an hour-old page, token already dead.
        stale = _cover("parse2-stale")
        asyncio.run(api._warm_era_art(_artist(("Donda", stale)), TRACKER))

        r = TestClient(app).get("/image-proxy", params={"url": stale})
        assert r.status_code == 200
        assert r.content == _png()

    def test_an_era_never_fetched_successfully_still_falls_through_upstream(self, google):
        stale = _cover("never-good")
        asyncio.run(api._warm_era_art(_artist(("Yandhi", stale)), TRACKER))
        r = TestClient(app).get("/image-proxy", params={"url": stale, "w": 320})
        assert r.status_code == 403

    def test_covers_from_another_tracker_are_not_borrowed(self, google):
        good = _cover("other-tracker")
        google.alive.add(good)
        asyncio.run(api._warm_era_art(_artist(("Donda", good)), "https://example-tracker.net/"))

        stale = _cover("ye-stale")
        asyncio.run(api._warm_era_art(_artist(("Donda", stale)), TRACKER))
        r = TestClient(app).get("/image-proxy", params={"url": stale})
        assert r.status_code == 403

    def test_a_rewarm_marks_the_current_cover_recently_used(self, google):
        """Eviction drops the oldest mtime first; a cover the live parse still
        points at must not be dated to its first download."""
        import os

        url = _cover("stable")
        google.alive.add(url)
        asyncio.run(api._warm_era_art(_artist(("Donda", url)), TRACKER))
        bin_path, _meta = api._image_cache_paths(api._image_cache_key(url, None))
        os.utime(bin_path, (1, 1))

        asyncio.run(api._warm_era_art(_artist(("Donda", url)), TRACKER))
        assert bin_path.stat().st_mtime > 1

    def test_overlapping_warms_keep_each_others_last_good_covers(self, google):
        donda, yandhi = _cover("donda"), _cover("yandhi")
        google.alive.update({donda, yandhi})

        async def both():
            await asyncio.gather(
                api._warm_era_art(_artist(("Donda", donda)), TRACKER),
                api._warm_era_art(_artist(("Yandhi", yandhi)), TRACKER),
            )

        asyncio.run(both())
        assert api._read_era_art_index(TRACKER) == {"Donda": donda, "Yandhi": yandhi}


class TestImageProxyReads:
    def test_a_thumbnail_hit_never_reads_the_original(self, google, monkeypatch):
        url = _cover("thumb")
        google.alive.add(url)
        asyncio.run(api._warm_era_art(_artist(("Donda", url)), TRACKER))
        api._write_image_cache(api._image_cache_key(url, 320), _png(320, 320), "image/png")
        client = TestClient(app)

        reads: list[str] = []
        real_read = api._read_image_cache
        monkeypatch.setattr(api, "_read_image_cache", lambda key: reads.append(key) or real_read(key))
        r = client.get("/image-proxy", params={"url": url, "w": 320})
        assert r.headers["x-cache-status"] == "hit"
        assert reads == [api._image_cache_key(url, 320)]


class TestWarmRunsAfterEveryServerParse:
    def _record(self, monkeypatch) -> list[str]:
        calls: list[str] = []

        def fake_warm(artist, tracker_url):
            calls.append(tracker_url)
            return asyncio.sleep(0)

        monkeypatch.setattr(api, "_warm_era_art", fake_warm)
        return calls

    def test_a_cold_parse_warms_its_covers(self, monkeypatch, tmp_path):
        calls = self._record(monkeypatch)
        monkeypatch.setattr(api, "CACHE_DIR", tmp_path)

        async def fake_fetch(url, **kwargs):
            return _artist(("Donda", _cover("x")))

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        r = TestClient(app).post("/sheet", json={"url": TRACKER, "use_cache": False})
        assert r.status_code == 200
        assert calls == [TRACKER]

    def test_a_background_revalidation_warms_its_covers(self, monkeypatch):
        calls = self._record(monkeypatch)

        async def fake_fetch(url, **kwargs):
            return _artist(("Donda", _cover("x")))

        monkeypatch.setattr(api, "async_fetch_and_parse", fake_fetch)
        asyncio.run(api._background_revalidate(TRACKER))
        assert calls == [TRACKER]
