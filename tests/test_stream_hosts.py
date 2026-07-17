"""Tests for pixeldrain.com and drive.google.com streaming support.

Covers URL resolution (resolve_stream_url / resolve_metadata_url), the
pixeldrain metadata parser, the stream-proxy domain allowlist, the Google
Drive virus-scan interstitial confirm-form parser, and the content-type gate
used to decide whether a gdrive response is safe to proxy as media.

No test in this file hits the live network — all upstream interaction is
either a pure function or is mocked.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import src.api as api
from src.api import (
    _STREAM_ALLOWED_DOMAINS,
    _is_allowed_domain,
    _media_kind_from_mime,
    _parse_pixeldrain_metadata,
    app,
)
from src.streaming import (
    GdriveInterstitialError,
    _is_gdrive_playable_content_type,
    build_gdrive_confirm_url,
    is_gdrive_url,
    parse_gdrive_confirm_form,
    resolve_metadata_url,
    resolve_stream_url,
)


# ---------------------------------------------------------------------------
# pixeldrain.com — resolve_stream_url
# ---------------------------------------------------------------------------


class TestPixeldrainStreamResolution:
    def test_file_url_resolves_to_api(self):
        url = "https://pixeldrain.com/u/abc123XYZ"
        assert resolve_stream_url(url) == "https://pixeldrain.com/api/file/abc123XYZ"

    def test_bare_domain_no_www(self):
        url = "https://www.pixeldrain.com/u/abc123"
        assert resolve_stream_url(url) == "https://pixeldrain.com/api/file/abc123"

    def test_list_url_is_not_resolved(self):
        # /l/ is a list of files, not a single file — must be ignored this
        # round, not silently treated as a file id.
        url = "https://pixeldrain.com/l/abc123XYZ"
        assert resolve_stream_url(url) is None

    def test_malformed_id_rejected(self):
        # No id at all after /u/ — nothing for the alnum pattern to match.
        url = "https://pixeldrain.com/u/"
        assert resolve_stream_url(url) is None

    def test_unrelated_url_not_matched(self):
        assert resolve_stream_url("https://pixeldrain.com/") is None


class TestPixeldrainMetadataResolution:
    def test_resolves_info_endpoint(self):
        url = "https://pixeldrain.com/u/abc123XYZ"
        result = resolve_metadata_url(url)
        assert result == {
            "url": "https://pixeldrain.com/api/file/abc123XYZ/info",
            "provider": "pixeldrain",
        }

    def test_list_url_has_no_metadata(self):
        url = "https://pixeldrain.com/l/abc123XYZ"
        assert resolve_metadata_url(url) is None


class TestParsePixeldrainMetadata:
    def test_audio_file(self):
        data = {"name": "track.flac", "size": 40000000, "mime_type": "audio/flac"}
        result = _parse_pixeldrain_metadata(data)
        assert result == {
            "provider": "pixeldrain",
            "filename": "track.flac",
            "file_size": 40000000,
            "mime_type": "audio/flac",
            "media_kind": "audio",
        }

    def test_video_file(self):
        data = {"name": "clip.mp4", "size": 123456, "mime_type": "video/mp4"}
        result = _parse_pixeldrain_metadata(data)
        assert result["media_kind"] == "video"
        assert result["mime_type"] == "video/mp4"

    def test_unknown_mime_falls_back(self):
        data = {"name": "file.bin", "size": 10, "mime_type": "application/octet-stream"}
        result = _parse_pixeldrain_metadata(data)
        assert result["media_kind"] == "unknown"

    def test_missing_fields_omitted(self):
        result = _parse_pixeldrain_metadata({})
        assert result == {"provider": "pixeldrain", "media_kind": "unknown"}
        assert "filename" not in result
        assert "file_size" not in result
        assert "mime_type" not in result

    def test_media_kind_uses_shared_helper(self):
        # Sanity check that _parse_pixeldrain_metadata actually reuses
        # _media_kind_from_mime rather than reimplementing classification.
        assert _media_kind_from_mime("audio/mpeg") == "audio"
        assert _parse_pixeldrain_metadata({"mime_type": "audio/mpeg"})["media_kind"] == "audio"


# ---------------------------------------------------------------------------
# drive.google.com — resolve_stream_url
# ---------------------------------------------------------------------------


class TestGdriveStreamResolution:
    def test_file_d_view_form(self):
        url = "https://drive.google.com/file/d/1a2B3c-_XYZ/view?usp=sharing"
        assert resolve_stream_url(url) == (
            "https://drive.google.com/uc?export=download&id=1a2B3c-_XYZ"
        )

    def test_open_id_form(self):
        url = "https://drive.google.com/open?id=1a2B3c-_XYZ"
        assert resolve_stream_url(url) == (
            "https://drive.google.com/uc?export=download&id=1a2B3c-_XYZ"
        )

    def test_uc_id_form(self):
        url = "https://drive.google.com/uc?id=1a2B3c-_XYZ&export=view"
        assert resolve_stream_url(url) == (
            "https://drive.google.com/uc?export=download&id=1a2B3c-_XYZ"
        )

    def test_uc_id_form_id_not_first_param(self):
        # id can appear anywhere in the query string.
        url = "https://drive.google.com/uc?export=view&id=1a2B3c-_XYZ"
        assert resolve_stream_url(url) == (
            "https://drive.google.com/uc?export=download&id=1a2B3c-_XYZ"
        )

    def test_malformed_id_rejected(self):
        # Id contains a character outside [A-Za-z0-9_-] (a slash) — reject
        # rather than silently truncating.
        url = "https://drive.google.com/open?id=abc/def"
        assert resolve_stream_url(url) is None

    def test_missing_id_rejected(self):
        assert resolve_stream_url("https://drive.google.com/open") is None

    def test_unrelated_drive_path_not_matched(self):
        assert resolve_stream_url("https://drive.google.com/drive/folders/xyz") is None

    def test_is_gdrive_url_helper(self):
        assert is_gdrive_url("https://drive.google.com/file/d/abc123/view") is True
        assert is_gdrive_url("https://drive.google.com/open?id=abc123") is True
        assert is_gdrive_url("https://pixeldrain.com/u/abc123") is False


class TestGdriveMetadataResolution:
    def test_no_metadata_provider_this_round(self):
        url = "https://drive.google.com/file/d/1a2B3c-_XYZ/view"
        assert resolve_metadata_url(url) is None


# ---------------------------------------------------------------------------
# Stream-proxy domain allowlist
# ---------------------------------------------------------------------------


class TestStreamAllowlist:
    @pytest.mark.parametrize("host", ["pixeldrain.com", "drive.google.com", "drive.usercontent.google.com"])
    def test_new_hosts_allowed(self, host):
        assert _is_allowed_domain(f"https://{host}/some/path", _STREAM_ALLOWED_DOMAINS) is True

    def test_evil_domain_rejected(self):
        assert _is_allowed_domain("https://evil.com/x", _STREAM_ALLOWED_DOMAINS) is False

    def test_pixeldrain_lookalike_subdomain_rejected(self):
        # A naive substring/suffix check could be fooled by an attacker
        # registering pixeldrain.com.evil.com; exact-hostname matching must
        # reject it.
        assert _is_allowed_domain(
            "https://pixeldrain.com.evil.com/u/x", _STREAM_ALLOWED_DOMAINS
        ) is False

    def test_gdrive_lookalike_subdomain_rejected(self):
        assert _is_allowed_domain(
            "https://drive.google.com.evil.com/uc", _STREAM_ALLOWED_DOMAINS
        ) is False


# ---------------------------------------------------------------------------
# Google Drive virus-scan interstitial — confirm-form parser
# ---------------------------------------------------------------------------

GDRIVE_INTERSTITIAL_HTML = """
<html><body>
<form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
<input type="hidden" name="id" value="1a2B3c-_XYZ">
<input type="hidden" name="export" value="download">
<input type="hidden" name="authuser" value="0">
<input type="hidden" name="confirm" value="t">
<input type="hidden" name="uuid" value="abcd-1234-ef56-7890">
<p>Google Drive can't scan this file for viruses.</p>
</form>
</body></html>
"""

GDRIVE_INTERSTITIAL_HTML_SINGLE_QUOTES = """
<html><body>
<form action='https://drive.usercontent.google.com/download' method='get'>
<input type='hidden' name='id' value='1a2B3c-_XYZ'>
<input type='hidden' name='confirm' value='t'>
</form>
</body></html>
"""

GDRIVE_PERMISSION_DENIED_HTML = """
<html><body>
<p>Sorry, you can't view or download this file at this time.</p>
</body></html>
"""


class TestParseGdriveConfirmForm:
    def test_extracts_hidden_fields(self):
        fields = parse_gdrive_confirm_form(GDRIVE_INTERSTITIAL_HTML)
        assert fields == {
            "id": "1a2B3c-_XYZ",
            "export": "download",
            "authuser": "0",
            "confirm": "t",
            "uuid": "abcd-1234-ef56-7890",
        }

    def test_handles_single_quoted_attributes(self):
        fields = parse_gdrive_confirm_form(GDRIVE_INTERSTITIAL_HTML_SINGLE_QUOTES)
        assert fields == {"id": "1a2B3c-_XYZ", "confirm": "t"}

    def test_no_form_returns_none(self):
        assert parse_gdrive_confirm_form(GDRIVE_PERMISSION_DENIED_HTML) is None

    def test_empty_html_returns_none(self):
        assert parse_gdrive_confirm_form("") is None

    def test_hidden_inputs_without_id_or_confirm_returns_none(self):
        html = '<input type="hidden" name="foo" value="bar">'
        assert parse_gdrive_confirm_form(html) is None


class TestBuildGdriveConfirmUrl:
    def test_builds_query_string(self):
        fields = {"id": "1a2B3c-_XYZ", "export": "download", "confirm": "t", "uuid": "abcd"}
        url = build_gdrive_confirm_url(fields)
        assert url.startswith("https://drive.usercontent.google.com/download?")
        assert "id=1a2B3c-_XYZ" in url
        assert "confirm=t" in url
        assert "uuid=abcd" in url


# ---------------------------------------------------------------------------
# Google Drive content-type gate
# ---------------------------------------------------------------------------


class TestGdrivePlayableContentType:
    @pytest.mark.parametrize("ct", [
        "audio/mpeg",
        "audio/flac",
        "video/mp4",
        "video/webm",
        "application/octet-stream",
        "binary/octet-stream",
        "audio/mp4; charset=binary",
    ])
    def test_allowed_types(self, ct):
        assert _is_gdrive_playable_content_type(ct) is True

    @pytest.mark.parametrize("ct", [
        "text/html",
        "text/html; charset=utf-8",
        "application/json",
        "text/plain",
    ])
    def test_rejected_types(self, ct):
        assert _is_gdrive_playable_content_type(ct) is False


# ---------------------------------------------------------------------------
# GdriveInterstitialError is a plain, importable exception type
# ---------------------------------------------------------------------------


def test_gdrive_interstitial_error_is_an_exception():
    with pytest.raises(GdriveInterstitialError):
        raise GdriveInterstitialError("boom")


# ---------------------------------------------------------------------------
# /stream endpoint — gdrive error mapping (stream_audio mocked; no network)
# ---------------------------------------------------------------------------

GDRIVE_SHARE_URL = "https://drive.google.com/file/d/abc123XYZ/view?usp=sharing"


class FakeUpstreamResponse:
    """Minimal stand-in for the httpx.Response stream_audio() returns."""

    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}

    async def aclose(self):
        pass


class TestStreamEndpointGdriveMapping:
    def test_persistent_interstitial_maps_to_409(self, monkeypatch):
        async def fake_stream_audio(url, *, range_header=None):
            raise GdriveInterstitialError("interstitial persisted after confirm retry")

        monkeypatch.setattr(api, "stream_audio", fake_stream_audio)
        client = TestClient(app)
        r = client.get("/stream", params={"url": GDRIVE_SHARE_URL})
        assert r.status_code == 409
        assert r.json()["detail"] == "gdrive_interstitial"

    def test_permission_denied_maps_to_403(self, monkeypatch):
        async def fake_stream_audio(url, *, range_header=None):
            return FakeUpstreamResponse(403)

        monkeypatch.setattr(api, "stream_audio", fake_stream_audio)
        client = TestClient(app)
        r = client.get("/stream", params={"url": GDRIVE_SHARE_URL})
        assert r.status_code == 403

    def test_generic_upstream_error_still_maps_to_502(self, monkeypatch):
        # Non-gdrive-specific failures must keep their existing 502 mapping —
        # the new 409/403 branches must not swallow other ValueErrors.
        async def fake_stream_audio(url, *, range_header=None):
            raise ValueError("Upstream returned 500")

        monkeypatch.setattr(api, "stream_audio", fake_stream_audio)
        client = TestClient(app)
        r = client.get("/stream", params={"url": GDRIVE_SHARE_URL})
        assert r.status_code == 502

    def test_unresolvable_url_still_400s(self):
        client = TestClient(app)
        r = client.get("/stream", params={"url": "https://not-a-supported-host.example/x"})
        assert r.status_code == 400
