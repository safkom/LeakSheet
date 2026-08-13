"""Tests for /image-proxy resizing, caching, and header behavior."""

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import src.api as api
from src.api import (
    _image_cache_key,
    _read_image_cache,
    _resize_image_bytes,
    _rewrite_google_size,
    _snap_image_width,
    _write_image_cache,
    app,
)


def make_png(width: int, height: int, mode: str = "RGB") -> bytes:
    img = Image.new(mode, (width, height), (200, 100, 50) if mode == "RGB" else None)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestRewriteGoogleSize:
    def test_lh3_with_size_suffix(self):
        url = "https://lh3.googleusercontent.com/abc123=w200-h200"
        assert _rewrite_google_size(url, 320) == "https://lh3.googleusercontent.com/abc123=s320"

    def test_lh6_without_suffix(self):
        url = "https://lh6.googleusercontent.com/abc123"
        assert _rewrite_google_size(url, 128) == "https://lh6.googleusercontent.com/abc123=s128"

    def test_s0_suffix_replaced(self):
        url = "https://lh4.googleusercontent.com/abc=s0"
        assert _rewrite_google_size(url, 640) == "https://lh4.googleusercontent.com/abc=s640"

    def test_lh7_rt_not_resizable(self):
        assert _rewrite_google_size("https://lh7-rt.googleusercontent.com/x?key=1", 320) is None

    def test_sheets_images_not_resizable(self):
        assert _rewrite_google_size("https://docs.google.com/sheets-images/abc", 320) is None

    def test_non_google_not_resizable(self):
        assert _rewrite_google_size("https://example.com/img.png", 320) is None

    def test_rewrite_preserves_host_and_path(self):
        url = "https://lh3.googleusercontent.com/some/path=w99"
        out = _rewrite_google_size(url, 128)
        assert out.startswith("https://lh3.googleusercontent.com/some/path")

    def test_no_upscale_option_suffix_stripped(self):
        """Google's option tokens aren't limited to s/w/h + digits — "no"
        (don't upscale), "c" (crop) etc. have no trailing number and must
        still be recognized as part of the suffix to strip."""
        url = "https://lh3.googleusercontent.com/d/ABC=w1000-h1000-no"
        assert _rewrite_google_size(url, 320) == "https://lh3.googleusercontent.com/d/ABC=s320"

    def test_crop_option_suffix_stripped(self):
        url = "https://lh3.googleusercontent.com/d/ABC=w1000-h1000-c"
        assert _rewrite_google_size(url, 320) == "https://lh3.googleusercontent.com/d/ABC=s320"


class TestSnapWidth:
    # 2026-07-17: 1600 bucket added — the old 1280 top bucket was below
    # iPhone full-screen width (~1290px), forcing an upscale on device.
    @pytest.mark.parametrize("requested,expected", [
        (32, 128), (128, 128), (129, 320), (320, 320),
        (321, 640), (640, 640), (641, 1280), (1280, 1280),
        (1290, 1600), (1600, 1600), (1601, 1600),
    ])
    def test_buckets(self, requested, expected):
        assert _snap_image_width(requested) == expected


class TestResizeImageBytes:
    def test_downscales_wide_image(self):
        data = make_png(800, 600)
        out, ct = _resize_image_bytes(data, 320, "image/png")
        assert ct == "image/jpeg"
        img = Image.open(io.BytesIO(out))
        assert img.width == 320
        assert img.height == 240  # aspect preserved

    def test_small_image_passthrough(self):
        data = make_png(100, 100)
        out, ct = _resize_image_bytes(data, 320, "image/png")
        assert out == data
        assert ct == "image/png"

    def test_alpha_stays_png(self):
        data = make_png(800, 600, mode="RGBA")
        out, ct = _resize_image_bytes(data, 320, "image/png")
        assert ct == "image/png"
        assert Image.open(io.BytesIO(out)).width == 320

    def test_undecodable_passthrough(self):
        data = b"definitely not an image"
        out, ct = _resize_image_bytes(data, 320, "image/png")
        assert out == data

    def test_oversized_input_passthrough(self):
        data = b"x" * (api._IMAGE_RESIZE_INPUT_CAP + 1)
        out, _ = _resize_image_bytes(data, 320, "image/png")
        assert out is data

    def test_decompression_bomb_passthrough(self, monkeypatch):
        """A small, highly-compressible file that would decode to a huge
        bitmap must be rejected by pixel count before img.load() runs —
        never actually decoded."""
        monkeypatch.setattr(api, "_IMAGE_MAX_DECODE_PIXELS", 100)

        class FakeImg:
            width, height = 10_000, 10_000

            def load(self):
                raise AssertionError("load() must not be called past the pixel cap")

        monkeypatch.setattr(Image, "open", lambda _buf: FakeImg())
        data = b"tiny but decodes huge"
        out, ct = _resize_image_bytes(data, 320, "image/png")
        assert out == data
        assert ct == "image/png"


class TestImageCacheKey:
    def test_stable(self):
        assert _image_cache_key("https://x/y", 320) == _image_cache_key("https://x/y", 320)

    def test_width_sensitive(self):
        assert _image_cache_key("https://x/y", 320) != _image_cache_key("https://x/y", 640)
        assert _image_cache_key("https://x/y", None) != _image_cache_key("https://x/y", 320)


class TestImageCacheWrite:
    def test_write_then_read_roundtrips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api, "CACHE_DIR", tmp_path)
        _write_image_cache("k1", b"hello world", "image/jpeg")
        data, ct, _etag = _read_image_cache("k1")
        assert data == b"hello world"
        assert ct == "image/jpeg"

    def test_rewrite_never_exposes_truncated_bytes(self, tmp_path, monkeypatch):
        """A reader landing between a rewrite's unlink and its replace must
        never see a shorter/partial file — write goes through a temp file
        + atomic rename, never an in-place truncate."""
        monkeypatch.setattr(api, "CACHE_DIR", tmp_path)
        _write_image_cache("k1", b"x" * 1000, "image/jpeg")
        bin_path, _ = api._image_cache_paths("k1")
        assert bin_path.stat().st_size == 1000

        _write_image_cache("k1", b"y" * 10, "image/jpeg")
        assert bin_path.stat().st_size == 10
        data, _, _ = _read_image_cache("k1")
        assert data == b"y" * 10

        # No leftover temp files after a clean write.
        assert list(tmp_path.glob("*.tmp*")) == []

    def test_write_failure_leaves_no_temp_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api, "CACHE_DIR", tmp_path)

        def boom(_src, _dst):
            raise OSError("disk full")

        monkeypatch.setattr(api.os, "replace", boom)
        # _write_image_cache swallows OSError from the atomic-write helper.
        _write_image_cache("k1", b"data", "image/jpeg")
        assert list(tmp_path.glob("*")) == []


class FakeResponse:
    def __init__(self, content: bytes, content_type: str = "image/png", status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.closed = False

    async def aiter_bytes(self):
        # Two chunks, so a test that caps mid-body sees a partial read the
        # way a real streamed response would.
        mid = len(self.content) // 2
        yield self.content[:mid]
        yield self.content[mid:]

    async def aclose(self):
        self.closed = True


class FakeClient:
    """Records requested URLs and serves a fixed image.

    Models the streaming API (build_request + send(stream=True)), because
    /image-proxy streams with a byte cap rather than buffering the whole
    body — a .get()-only double would no longer exercise the real path.
    """

    def __init__(self, content: bytes, content_type: str = "image/png"):
        self._content = content
        self._content_type = content_type
        self.requested: list[str] = []
        self.responses: list[FakeResponse] = []

    async def get(self, url, headers=None):
        self.requested.append(url)
        return FakeResponse(self._content, self._content_type)

    def build_request(self, method, url, headers=None):
        return SimpleNamespace(method=method, url=url, headers=headers)

    async def send(self, request, stream=False):
        self.requested.append(request.url)
        resp = FakeResponse(self._content, self._content_type)
        self.responses.append(resp)
        return resp


@pytest.fixture()
def proxy_env(monkeypatch, tmp_path):
    """TestClient with a fake upstream and an isolated cache dir."""
    fake = FakeClient(make_png(800, 600))
    monkeypatch.setattr(api, "_get_proxy_client", lambda: fake)
    monkeypatch.setattr(api, "CACHE_DIR", tmp_path)
    return TestClient(app), fake


NON_GOOGLE_URL = "https://ggpht.com/some/image"
GOOGLE_URL = "https://lh3.googleusercontent.com/abc=w120"


class TestImageProxyEndpoint:
    def test_plain_passthrough(self, proxy_env):
        client, fake = proxy_env
        r = client.get("/image-proxy", params={"url": NON_GOOGLE_URL})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "origin"
        # Unsized requests are never disk-cached, so there's nothing to
        # validate a future revalidation against — no ETag should be sent.
        assert "ETag" not in r.headers
        assert r.headers.get("content-encoding") != "gzip"
        assert fake.requested == [NON_GOOGLE_URL]

    def test_w_resizes_and_caches(self, proxy_env):
        client, fake = proxy_env
        r = client.get("/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "miss"
        assert Image.open(io.BytesIO(r.content)).width == 320

        r2 = client.get("/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320})
        assert r2.headers["X-Cache-Status"] == "hit"
        assert len(fake.requested) == 1  # second request served from disk
        assert r2.content == r.content

    def test_google_side_resize_skips_pillow(self, proxy_env):
        client, fake = proxy_env
        r = client.get("/image-proxy", params={"url": GOOGLE_URL, "w": 320})
        assert r.status_code == 200
        assert r.headers["X-Cache-Status"] == "origin"
        assert fake.requested == ["https://lh3.googleusercontent.com/abc=s320"]

    def test_if_none_match_304(self, proxy_env):
        client, fake = proxy_env
        r = client.get("/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320})
        etag = r.headers["ETag"]
        r2 = client.get(
            "/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320},
            headers={"If-None-Match": etag},
        )
        assert r2.status_code == 304
        assert len(fake.requested) == 1

    def test_if_none_match_refetches_after_the_entry_is_rewritten(self, proxy_env):
        """The ETag identifies the BYTES, not the request.

        It used to be a bare hash of (url, width). After the 7-day TTL expired
        and the URL was refetched with different content, the key was
        identical — so a client holding the OLD bytes sent If-None-Match, got
        a 304, and kept showing a stale image forever.
        """
        client, fake = proxy_env
        r = client.get("/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320})
        old_etag = r.headers["ETag"]

        # Rewrite the same key with new content, as a post-TTL refetch does.
        import time as _time
        key = _image_cache_key(NON_GOOGLE_URL, 320)
        _time.sleep(1.1)  # the tag carries whole-second write time
        _write_image_cache(key, b"different bytes entirely", "image/jpeg")

        r2 = client.get(
            "/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320},
            headers={"If-None-Match": old_etag},
        )
        assert r2.status_code == 200, "a rewritten entry must not answer 304"
        assert r2.headers["ETag"] != old_etag

    def test_if_none_match_refetches_after_cache_cleared(self, proxy_env):
        """A stale ETag must not 304 once its backing cache entry is gone —
        otherwise updated upstream art (or /cache/clear) could never be
        observed by a client holding an old ETag."""
        client, fake = proxy_env
        r = client.get("/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320})
        etag = r.headers["ETag"]

        for p in api.CACHE_DIR.glob("img_*"):
            p.unlink()

        r2 = client.get(
            "/image-proxy", params={"url": NON_GOOGLE_URL, "w": 320},
            headers={"If-None-Match": etag},
        )
        assert r2.status_code == 200
        assert r2.headers["X-Cache-Status"] == "miss"
        assert len(fake.requested) == 2

    def test_disallowed_domain_rejected_with_w(self, proxy_env):
        client, _ = proxy_env
        r = client.get("/image-proxy", params={"url": "https://evil.example/img", "w": 320})
        assert r.status_code == 403

    def test_w_out_of_range_rejected(self, proxy_env):
        client, _ = proxy_env
        assert client.get("/image-proxy", params={"url": NON_GOOGLE_URL, "w": 10}).status_code == 422
        assert client.get("/image-proxy", params={"url": NON_GOOGLE_URL, "w": 9000}).status_code == 422

    def test_oversized_body_is_abandoned(self, monkeypatch, tmp_path):
        """A body larger than the download cap must not be buffered.

        /image-proxy used a non-streaming .get(), so the whole body landed in
        memory before the content-type check, and the existing size caps only
        ran inside _resize_image_bytes — after the fact, and only when `w` was
        given. The allowlist admits any *.google.com host, so an oversized
        Drive file was enough to OOM the worker.
        """
        monkeypatch.setattr(api, "_IMAGE_DOWNLOAD_CAP", 1024)
        fake = FakeClient(b"\x89PNG" + b"x" * 8192)
        monkeypatch.setattr(api, "_get_proxy_client", lambda: fake)
        monkeypatch.setattr(api, "CACHE_DIR", tmp_path)

        r = TestClient(app).get("/image-proxy", params={"url": NON_GOOGLE_URL})
        assert r.status_code == 502
        # The streamed response is closed even on the reject path, so the
        # upstream connection is returned to the pool rather than leaked.
        assert fake.responses and fake.responses[-1].closed
