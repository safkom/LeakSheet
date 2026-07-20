"""Contract tests for GET /stream (audio proxy) with a fake upstream.

``src.api.stream_audio`` is stubbed with a fake streaming response so the
endpoint's own logic is what's under test: host resolution + allowlist, 206
passthrough, 200 full body, locally-synthesised 206 for a range an upstream
ignored, 416 relay, magic-byte MIME correction, and the download disposition.
"""

from __future__ import annotations

import pytest

import src.api as api

# A real supported link → resolve_stream_url maps it to api.pillows.su (allowed).
PILLOWS = "https://pillows.su/f/abc123"


class FakeStreamResponse:
    """Minimal stand-in for the httpx streaming response stream_audio returns."""

    def __init__(self, status_code, headers, chunks, url="https://api.pillows.su/api/get/abc123"):
        self.status_code = status_code
        self.headers = headers
        self._chunks = list(chunks)
        self.url = url

    async def aiter_bytes(self, chunk_size=65536):
        for c in self._chunks:
            yield c

    async def aclose(self):
        pass


def _patch_stream(monkeypatch, resp):
    async def fake_stream_audio(stream_url, *, range_header=None):
        fake_stream_audio.last_range = range_header
        return resp

    fake_stream_audio.last_range = None
    monkeypatch.setattr(api, "stream_audio", fake_stream_audio)
    return fake_stream_audio


class TestHostResolution:
    def test_unsupported_host_is_400(self, api_client):
        r = api_client.get("/stream", params={"url": "https://example.com/x.mp3"})
        assert r.status_code == 400

    def test_disallowed_resolved_domain_is_403(self, api_client, monkeypatch):
        # Defence in depth: if the resolver ever yields a non-allowlisted host,
        # the endpoint must still refuse it.
        monkeypatch.setattr(api, "resolve_stream_url", lambda u: "https://evil.example/x.mp3")
        r = api_client.get("/stream", params={"url": PILLOWS})
        assert r.status_code == 403

    def test_upstream_valueerror_is_502(self, api_client, monkeypatch):
        async def raiser(stream_url, *, range_header=None):
            raise ValueError("upstream returned non-audio content")

        monkeypatch.setattr(api, "stream_audio", raiser)
        r = api_client.get("/stream", params={"url": PILLOWS})
        assert r.status_code == 502


class TestPassthroughAndFull:
    def test_206_passthrough_derives_content_length_from_range(self, api_client, monkeypatch):
        _patch_stream(monkeypatch, FakeStreamResponse(
            206,
            {"content-type": "audio/mpeg", "content-range": "bytes 0-4/10", "content-length": "10"},
            [b"hello"],
        ))
        r = api_client.get("/stream", params={"url": PILLOWS}, headers={"Range": "bytes=0-4"})
        assert r.status_code == 206
        assert r.headers["content-range"] == "bytes 0-4/10"
        # Upstream reported the *total* (10) in content-length; endpoint corrects
        # it to the slice length (5) so iOS Safari seeking works.
        assert r.headers["content-length"] == "5"
        assert r.content == b"hello"

    def test_200_full_body_no_range(self, api_client, monkeypatch):
        _patch_stream(monkeypatch, FakeStreamResponse(
            200, {"content-type": "audio/mpeg", "content-length": "10"}, [b"hello", b"world"],
        ))
        r = api_client.get("/stream", params={"url": PILLOWS})
        assert r.status_code == 200
        assert r.content == b"helloworld"
        assert r.headers["accept-ranges"] == "bytes"


class TestSynthesizedRange:
    def test_200_upstream_plus_client_range_synthesises_206(self, api_client, monkeypatch):
        _patch_stream(monkeypatch, FakeStreamResponse(
            200, {"content-type": "audio/mpeg", "content-length": "10"}, [b"0123456789"],
        ))
        r = api_client.get("/stream", params={"url": PILLOWS}, headers={"Range": "bytes=2-5"})
        assert r.status_code == 206
        assert r.content == b"2345"
        assert r.headers["content-range"] == "bytes 2-5/10"
        assert r.headers["content-length"] == "4"

    def test_upstream_416_is_relayed(self, api_client, monkeypatch):
        _patch_stream(monkeypatch, FakeStreamResponse(
            416, {"content-range": "bytes */10"}, [],
        ))
        r = api_client.get("/stream", params={"url": PILLOWS}, headers={"Range": "bytes=1000-"})
        assert r.status_code == 416
        assert r.headers["content-range"] == "bytes */10"


class TestMimeAndDisposition:
    def test_ogg_magic_bytes_override_wrong_content_type(self, api_client, monkeypatch):
        # pillows.su always says audio/mp4; the real bytes are Ogg. Safari would
        # reject audio/mp4 for Ogg data, so the endpoint sniffs and corrects it.
        _patch_stream(monkeypatch, FakeStreamResponse(
            200, {"content-type": "audio/mp4", "content-length": "16"},
            [b"OggS\x00\x02\x00\x00realaudio"],
        ))
        r = api_client.get("/stream", params={"url": PILLOWS})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/ogg")

    def test_download_sets_content_disposition(self, api_client, monkeypatch):
        _patch_stream(monkeypatch, FakeStreamResponse(
            200, {"content-type": "audio/mpeg", "content-length": "5"}, [b"hello"],
        ))
        r = api_client.get("/stream", params={"url": PILLOWS, "download": "true"})
        assert r.status_code == 200
        assert r.headers["content-disposition"] == 'attachment; filename="track.mp3"'
