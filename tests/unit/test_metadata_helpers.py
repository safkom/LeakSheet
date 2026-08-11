"""Unit tests for /metadata parsing helpers and the in-memory TTL cache."""

from src.api import (
    _TTLCache,
    _derive_media_kind,
    _media_kind_from_mime,
    _parse_froste_metadata,
    _parse_imgur_metadata,
    _parse_pillows_metadata,
)

# The delimiter-less blob format pillows.su actually returns.
PILLOWS_BLOB = (
    "FILE FORMAT INFO:CONTAINER: MPEGCODEC: MPEG 1 Layer 3CODEC PROFILE: CBR"
    "DURATION: 139.8073469387755sBITRATE: 256kbpsSAMPLE RATE: 44100Hz"
    "BITS PER SAMPLE: unknownLOSSLESS: falseNUMBER OF CHANNELS: 2"
    "CREATION TIME: unknownMODIFICATION TIME: unknownTRACK GAIN: unknown"
    "ALBUM GAIN: unknownCOMMON INFO:ARTIST: unknownALBUM ARTIST: unknown"
    "ALBUM: unknownTITLE: unknownTRACK: nullGENRE: unknownDATE: unknown"
    "YEAR: 2019COMMENT: unknown"
)

PILLOWS_NEWLINES = """FILE FORMAT INFO:
CONTAINER: FLAC
CODEC: FLAC
DURATION: 210.5s
BITRATE: 1024kbps
SAMPLE RATE: 44100Hz
BITS PER SAMPLE: 16
LOSSLESS: true
NUMBER OF CHANNELS: stereo
COMMON INFO:
TITLE: Some Song
"""


class TestParsePillowsMetadata:
    def test_continuous_blob(self):
        result = _parse_pillows_metadata(PILLOWS_BLOB)
        assert result["provider"] == "pillows"
        assert result["container"] == "MPEG"
        assert result["codec"] == "MPEG 1 Layer 3"
        assert result["codec_profile"] == "CBR"
        assert result["bitrate"] == "256kbps"
        assert result["sample_rate"] == "44100Hz"
        assert result["lossless"] is False
        assert result["channels"] == 2
        assert result["duration"] == "139.8073469387755s"
        # "unknown"/"null" values are dropped
        assert "bits_per_sample" not in result
        assert "artist" not in result
        assert "title" not in result

    def test_newline_format(self):
        result = _parse_pillows_metadata(PILLOWS_NEWLINES)
        assert result["container"] == "FLAC"
        assert result["lossless"] is True
        assert result["bits_per_sample"] == "16"
        # non-digit channel counts survive as strings
        assert result["channels"] == "stereo"
        assert result["title"] == "Some Song"

    def test_empty_input(self):
        # 2026-07-17: media_kind is always derived (unknown when no signal)
        assert _parse_pillows_metadata("") == {
            "provider": "pillows",
            "media_kind": "unknown",
        }

    def test_video_file_flagged(self):
        """An mp4/H.264 behind an opaque pillows id — the only video signal
        clients get, since the pillows stream endpoint always says audio/mp4."""
        text = (
            "FILE FORMAT INFO:CONTAINER: MPEG-4CODEC: H.264"
            "CODEC PROFILE: High ProfileDURATION: 212.4s"
        )
        result = _parse_pillows_metadata(text)
        assert result["media_kind"] == "video"

    def test_audio_file_flagged(self):
        assert _parse_pillows_metadata(PILLOWS_BLOB)["media_kind"] == "audio"
        assert _parse_pillows_metadata(PILLOWS_NEWLINES)["media_kind"] == "audio"


class TestParseFrosteMetadata:
    def test_fields(self):
        result = _parse_froste_metadata(
            {"estimatedBitrate": 255.6, "frequencyCutoff": 19.94, "qualityMismatch": False}
        )
        assert result["provider"] == "froste"
        assert result["estimated_bitrate"] == 256
        assert result["bitrate"] == "256kbps"
        assert result["frequency_cutoff"] == 19.9
        assert result["quality_mismatch"] is False

    def test_empty(self):
        assert _parse_froste_metadata({}) == {"provider": "froste"}


class TestParseImgurMetadata:
    def test_fields(self):
        result = _parse_imgur_metadata(
            {"size": 12345, "mimeType": "audio/mpeg", "name": "song.mp3"}
        )
        # 2026-07-17: media_kind derived from the mime type
        assert result == {
            "provider": "imgur",
            "file_size": 12345,
            "mime_type": "audio/mpeg",
            "filename": "song.mp3",
            "media_kind": "audio",
        }

    def test_video_mime_flagged(self):
        result = _parse_imgur_metadata({"mimeType": "video/mp4", "name": "clip.mp4"})
        assert result["media_kind"] == "video"

    def test_live_api_type_key(self):
        # The real imgur.gg response uses "type", not "mimeType" — reading
        # only the latter made every live response report media_kind
        # "unknown" (verified against the live API, 2026-08).
        result = _parse_imgur_metadata(
            {"size": 7899713, "type": "video/mp4", "name": "clip.mp4"}
        )
        assert result["mime_type"] == "video/mp4"
        assert result["media_kind"] == "video"


class TestDeriveMediaKind:
    def test_video_codecs(self):
        for codec in ("H.264 High Profile", "h264", "HEVC", "AV1", "VP9", "MPEG-4 Video"):
            assert _derive_media_kind("MPEG-4", codec) == "video", codec

    def test_audio_codecs(self):
        for codec in ("AAC LC", "MPEG 1 Layer 3", "FLAC", "ALAC", "Opus", "PCM"):
            assert _derive_media_kind("MPEG-4", codec) == "audio", codec

    def test_audio_container_without_codec(self):
        for container in ("FLAC", "WAV", "Ogg", "AIFF"):
            assert _derive_media_kind(container, None) == "audio", container

    def test_ambiguous_container_is_unknown(self):
        # mp4/mov hold audio-only m4a files too — container alone can't decide
        for container in ("MPEG-4", "MOV", "Matroska", "WebM"):
            assert _derive_media_kind(container, None) == "unknown", container

    def test_no_signal_is_unknown(self):
        assert _derive_media_kind(None, None) == "unknown"

    def test_mime_helper(self):
        assert _media_kind_from_mime("video/mp4") == "video"
        assert _media_kind_from_mime("audio/mpeg; charset=binary") == "audio"
        assert _media_kind_from_mime("application/octet-stream") == "unknown"
        assert _media_kind_from_mime(None) == "unknown"


class TestTTLCache:
    def test_set_get(self):
        cache = _TTLCache(ttl=60, max_entries=10)
        cache.set("a", "1")
        assert cache.get("a") == "1"
        assert cache.get("missing") is None

    def test_expiry(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr("src.api.time.monotonic", lambda: now[0])
        cache = _TTLCache(ttl=10, max_entries=10)
        cache.set("a", "1")
        now[0] += 5
        assert cache.get("a") == "1"
        now[0] += 6
        assert cache.get("a") is None

    def test_cap_evicts_oldest(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr("src.api.time.monotonic", lambda: now[0])
        cache = _TTLCache(ttl=1000, max_entries=3)
        for i, key in enumerate(["a", "b", "c"]):
            now[0] += 1
            cache.set(key, str(i))
        now[0] += 1
        cache.set("d", "3")
        assert cache.get("a") is None  # oldest evicted
        assert cache.get("b") == "1"
        assert cache.get("d") == "3"

    def test_overwrite_does_not_evict(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr("src.api.time.monotonic", lambda: now[0])
        cache = _TTLCache(ttl=1000, max_entries=2)
        cache.set("a", "1")
        now[0] += 1
        cache.set("b", "2")
        now[0] += 1
        cache.set("a", "updated")  # existing key: no eviction
        assert cache.get("b") == "2"
        assert cache.get("a") == "updated"
