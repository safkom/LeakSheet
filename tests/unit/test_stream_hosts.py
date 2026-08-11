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

from src.api import (
    _STREAM_ALLOWED_DOMAINS,
    _is_allowed_domain,
    _media_kind_from_mime,
    _parse_pixeldrain_metadata,
)
from src.streaming import (
    GdriveInterstitialError,
    _is_audio_content_type,
    build_gdrive_confirm_url,
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


class TestGdriveMetadataResolution:
    def test_no_metadata_provider_this_round(self):
        url = "https://drive.google.com/file/d/1a2B3c-_XYZ/view"
        assert resolve_metadata_url(url) is None


# ---------------------------------------------------------------------------
# imgur.gg — resolve_stream_url / resolve_metadata_url
#
# Had zero coverage until 2026-08, which is why the upstream host flip
# (temp.imgur.gg started 404ing, imgur.gg started working) broke every
# imgur link silently.
# ---------------------------------------------------------------------------


class TestImgurResolution:
    @pytest.mark.parametrize("link", [
        "https://imgur.gg/f/002XdG5",
        "https://temp.imgur.gg/f/002XdG5",
        "https://www.imgur.gg/f/002XdG5",
    ])
    def test_resolves_to_live_api_host(self, link):
        # Every input form resolves to imgur.gg — NOT temp.imgur.gg, which
        # 404s. resolve_imgur_cdn_url keeps temp. as a runtime fallback.
        assert resolve_stream_url(link) == "https://imgur.gg/api/file/002XdG5"

    def test_metadata_url_uses_the_same_host(self):
        meta = resolve_metadata_url("https://imgur.gg/f/002XdG5")
        assert meta == {
            "url": "https://imgur.gg/api/file/002XdG5",
            "provider": "imgur",
        }

    def test_resolved_host_is_allowlisted(self):
        # The resolver and the proxy allowlist must not drift: a resolved
        # URL the proxy then rejects is a silent 403 on every playback.
        resolved = resolve_stream_url("https://imgur.gg/f/002XdG5")
        assert _is_allowed_domain(resolved, _STREAM_ALLOWED_DOMAINS) is True

    def test_mp4_container_is_playable(self):
        # imgur.gg serves audio inside an mp4 container and labels it
        # video/mp4; rejecting that is what produced the 502.
        assert _is_audio_content_type("video/mp4") is True


# ---------------------------------------------------------------------------
# Stream-proxy domain allowlist
# ---------------------------------------------------------------------------


class TestStreamAllowlist:
    def test_allowlist_is_exactly_the_resolver_output_hosts(self):
        # Single source of truth (2026-07-24): the proxy allowlist IS the set
        # of hosts resolve_stream_url can emit — nothing more, nothing less.
        assert _STREAM_ALLOWED_DOMAINS == {
            "api.pillows.su",
            # Both imgur hosts: resolve_stream_url emits imgur.gg and
            # resolve_imgur_cdn_url falls back to temp.imgur.gg.
            "imgur.gg",
            "temp.imgur.gg",
            "music.froste.lol",
            "krakenfiles.com",
            "pixeldrain.com",
            "drive.google.com",
        }

    @pytest.mark.parametrize("host", sorted(_STREAM_ALLOWED_DOMAINS))
    def test_allowed_hosts_pass(self, host):
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


class TestPlayableContentType:
    """One gate for every host (2026-08).

    gdrive used to have its own copy, `_is_gdrive_playable_content_type`,
    which accepted `video/*` while the general path did not — that gap is
    why imgur.gg (which serves audio in an mp4 container) 502'd.
    """

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
        assert _is_audio_content_type(ct) is True

    @pytest.mark.parametrize("ct", [
        "text/html",
        "text/html; charset=utf-8",
        "application/json",
        "text/plain",
    ])
    def test_rejected_types(self, ct):
        assert _is_audio_content_type(ct) is False


# ---------------------------------------------------------------------------
# GdriveInterstitialError is a plain, importable exception type
# ---------------------------------------------------------------------------


def test_gdrive_interstitial_error_is_an_exception():
    with pytest.raises(GdriveInterstitialError):
        raise GdriveInterstitialError("boom")


# NOTE: the /stream endpoint mapping tests for gdrive (409/403/502) live in
# tests/api/test_stream_endpoint.py — this module is pure functions only.


class TestUnmatchedLinkLogging:
    def test_unmatched_host_does_not_warn(self, caplog):
        """Non-streamable hosts are normal tracker content (YouTube, imgbb, …);
        census/health tooling probes every link, so a WARNING per miss floods
        logs. 2026-07-20 review: downgraded to debug."""
        import logging

        with caplog.at_level(logging.WARNING, logger="src.streaming"):
            assert resolve_stream_url("https://www.youtube.com/watch?v=x") is None
        assert caplog.records == []


class TestGdriveRedirectHosts:
    """2026-07-18: large public files redirect to *.googleusercontent.com —
    accept Google's storage CDN, reject everything else."""

    def test_googleusercontent_storage_hosts_allowed(self):
        from src.streaming import _is_gdrive_host_allowed
        assert _is_gdrive_host_allowed("https://doc-0k-8s-docs.googleusercontent.com/x")
        assert _is_gdrive_host_allowed("https://lh3.googleusercontent.com/d/abc")

    def test_non_google_hosts_rejected(self):
        from src.streaming import _is_gdrive_host_allowed
        assert not _is_gdrive_host_allowed("https://evil.com/googleusercontent.com")
        assert not _is_gdrive_host_allowed("https://googleusercontent.com.evil.com/x")
        assert not _is_gdrive_host_allowed("https://xgoogleusercontent.com/x")
