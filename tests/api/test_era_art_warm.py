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
        # 502, not the 403 Google gave us: an expired token is this server
        # holding a stale URL, not the caller being forbidden the image.
        assert r.status_code == 502

    def test_covers_from_another_tracker_are_not_borrowed(self, google):
        good = _cover("other-tracker")
        google.alive.add(good)
        asyncio.run(api._warm_era_art(_artist(("Donda", good)), "https://example-tracker.net/"))

        stale = _cover("ye-stale")
        asyncio.run(api._warm_era_art(_artist(("Donda", stale)), TRACKER))
        r = TestClient(app).get("/image-proxy", params={"url": stale})
        assert r.status_code == 502

    def test_a_rewarm_marks_the_current_cover_recently_used(self, google):
        """Eviction drops the oldest mtime first; a cover the live parse still
        points at must not be dated to its first download."""
        import os

        url = _cover("stable")
        google.alive.add(url)
        asyncio.run(api._warm_era_art(_artist(("Donda", url)), TRACKER))
        bin_path, _meta = api._image_cache_paths(
            api._image_cache_key(api._era_art_base(TRACKER, "Donda"), None)
        )
        os.utime(bin_path, (1, 1))

        asyncio.run(api._warm_era_art(_artist(("Donda", url)), TRACKER))
        assert bin_path.stat().st_mtime > 1

    def test_overlapping_warms_both_store_their_covers(self, google):
        donda, yandhi = _cover("donda"), _cover("yandhi")
        google.alive.update({donda, yandhi})

        async def both():
            await asyncio.gather(
                api._warm_era_art(_artist(("Donda", donda)), TRACKER),
                api._warm_era_art(_artist(("Yandhi", yandhi)), TRACKER),
            )

        asyncio.run(both())
        for era in ("Donda", "Yandhi"):
            key = api._image_cache_key(api._era_art_base(TRACKER, era), None)
            assert api._read_image_cache(key), era


class TestImageProxyReads:
    def test_a_thumbnail_hit_never_reads_the_original(self, google, monkeypatch):
        url = _cover("thumb")
        google.alive.add(url)
        asyncio.run(api._warm_era_art(_artist(("Donda", url)), TRACKER))
        api._write_image_cache(
            api._image_cache_key(api._era_art_base(TRACKER, "Donda"), 320),
            _png(320, 320), "image/png",
        )
        client = TestClient(app)

        reads: list[str] = []
        real_read = api._read_image_cache
        monkeypatch.setattr(api, "_read_image_cache", lambda key: reads.append(key) or real_read(key))
        r = client.get("/image-proxy", params={"url": url, "w": 320})
        assert r.headers["x-cache-status"] == "hit"
        assert reads == [api._image_cache_key(api._era_art_base(TRACKER, "Donda"), 320)]


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


class TestStableCoverKeying:
    """The cover cache is keyed on (tracker, era), not on Google's token URL.

    Keying on the URL meant every hourly reparse filed the same bytes under a
    new name and let the LRU evict the old one. A client holding a payload a
    few hours old then asked for an evicted entry, went upstream, and got
    Google's 403 on the expired token — 33 of 209 /image-proxy requests on
    2026-09-21, all from the iOS app.
    """

    @staticmethod
    def _covers(tmp_path):
        return sorted(p.name for p in tmp_path.glob("img_*.bin"))

    def test_a_reparse_reuses_one_entry_instead_of_minting_another(self, google, tmp_path):
        first, second = _cover("hour1"), _cover("hour2")
        google.alive.add(first)
        asyncio.run(api._warm_era_art(_artist(("Donda", first)), TRACKER))
        assert len(self._covers(tmp_path)) == 1

        # Next hour: same cover, freshly minted URL.
        google.alive.clear()
        google.alive.add(second)
        asyncio.run(api._warm_era_art(_artist(("Donda", second)), TRACKER))
        assert len(self._covers(tmp_path)) == 1, "a reparse must not add a second entry"

    def test_a_client_holding_last_hours_url_still_gets_the_cover(self, google):
        """The exact production failure, end to end."""
        old_url, new_url = _cover("payload-the-client-cached"), _cover("current-parse")
        google.alive.add(old_url)
        asyncio.run(api._warm_era_art(_artist(("Donda", old_url)), TRACKER))

        # An hour passes: the tracker is reparsed under a new token, and the
        # token the client still holds stops working.
        google.alive.clear()
        google.alive.add(new_url)
        asyncio.run(api._warm_era_art(_artist(("Donda", new_url)), TRACKER))
        google.alive.clear()
        google.requested.clear()

        r = TestClient(app).get("/image-proxy", params={"url": old_url, "w": 320})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        assert google.requested == [], "must be served from the slot, not upstream"

    def test_the_thumbnail_survives_a_reparse_too(self, google):
        """A resize done under one token is reused under the next.

        The thumbnail is written by hand for the same reason the test above
        does it: the solid-colour fixture does not get smaller when resized,
        and the proxy only caches a resize that actually shrank.
        """
        first, second = _cover("t1"), _cover("t2")
        google.alive.add(first)
        asyncio.run(api._warm_era_art(_artist(("Donda", first)), TRACKER))
        api._write_image_cache(
            api._image_cache_key(api._era_art_base(TRACKER, "Donda"), 320),
            _png(320, 320), "image/png",
        )

        google.alive.clear()
        google.alive.add(second)
        asyncio.run(api._warm_era_art(_artist(("Donda", second)), TRACKER))
        google.requested.clear()

        # Requested under the NEW token, served from the thumbnail cached
        # under the old one — because neither is keyed on the token.
        r = TestClient(app).get("/image-proxy", params={"url": second, "w": 320})
        assert r.status_code == 200
        assert r.headers["x-cache-status"] == "hit"
        assert google.requested == []

    def test_an_unwarmed_url_is_unaffected(self, google):
        """No alias, no change: a plain image still goes upstream as before."""
        url = _cover("never-warmed")
        google.alive.add(url)
        r = TestClient(app).get("/image-proxy", params={"url": url})
        assert r.status_code == 200
        assert google.requested == [url]

    def test_two_eras_of_one_tracker_get_different_slots(self, google):
        assert api._era_art_base(TRACKER, "Donda") != api._era_art_base(TRACKER, "Yandhi")

    def test_the_same_era_name_under_two_trackers_does_not_collide(self, google):
        assert api._era_art_base(TRACKER, "Donda") != api._era_art_base("https://other/", "Donda")

    def test_a_corrupt_alias_is_ignored_rather_than_used_as_a_key(self, google, tmp_path):
        url = _cover("corrupt")
        api._write_image_alias(url, "leaksheet:art/aa/bb")
        api._image_alias_path(url).write_text("../../etc/passwd")
        assert api._read_image_alias(url) is None
