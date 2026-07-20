"""Unit tests for /metadata parsing helpers and the in-memory TTL cache."""

from src.api import (
    _TTLCache,
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
        assert _parse_pillows_metadata("") == {"provider": "pillows"}


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
        assert result == {
            "provider": "imgur",
            "file_size": 12345,
            "mime_type": "audio/mpeg",
            "filename": "song.mp3",
        }


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
