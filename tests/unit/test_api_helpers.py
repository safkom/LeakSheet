"""Unit tests for small helpers in src/api.py.

Covers ETag parsing per RFC 7232 §2.3 (strong and weak forms).
"""

import pytest

from src.api import _parse_if_none_match, _plan_synthesized_range, _RangePlan


@pytest.mark.parametrize(
    ("header", "total", "expected"),
    [
        # No header / ignored headers → full 200
        (None, 1000, _RangePlan("full")),
        ("", 1000, _RangePlan("full")),
        ("bytes=abc", 1000, _RangePlan("full")),           # malformed → ignore
        ("bytes=0-1,5-9", 1000, _RangePlan("full")),       # multi-part → ignore
        ("items=0-5", 1000, _RangePlan("full")),           # non-bytes unit
        ("bytes=5-2", 1000, _RangePlan("full")),           # end < start → ignore
        # Closed ranges
        ("bytes=0-499", 1000, _RangePlan("partial", 0, 499)),
        ("bytes=500-999", 1000, _RangePlan("partial", 500, 999)),
        ("bytes=0-999999999", 1000, _RangePlan("partial", 0, 999)),   # clamp to total
        # Unknown total: we cannot clamp `end`, so we cannot honestly promise
        # a Content-Length. Serving the full body signals "Range unsupported";
        # synthesising a 206 advertised the REQUESTED length and then
        # delivered a shorter body. Matches the suffix/open-ended branches.
        ("bytes=0-499", None, _RangePlan("full")),
        ("bytes=0-999999999", None, _RangePlan("full")),
        # Open-ended ranges
        ("bytes=0-", 1000, _RangePlan("partial", 0, 999)),
        ("bytes=200-", 1000, _RangePlan("partial", 200, 999)),
        ("bytes=200-", None, _RangePlan("full")),          # unknown total → 200
        # Suffix ranges (AVPlayer reads trailing MP4 metadata this way)
        ("bytes=-500", 1000, _RangePlan("partial", 500, 999)),
        ("bytes=-2000", 1000, _RangePlan("partial", 0, 999)),  # suffix > total
        ("bytes=-500", None, _RangePlan("full")),          # unknown total → 200
        ("bytes=-0", 1000, _RangePlan("unsatisfiable")),   # names no bytes
        # Unsatisfiable starts
        ("bytes=1000-", 1000, _RangePlan("unsatisfiable")),
        ("bytes=1000-2000", 1000, _RangePlan("unsatisfiable")),
        ("bytes=999-", 1000, _RangePlan("partial", 999, 999)),  # last byte OK
    ],
)
def test_plan_synthesized_range(header, total, expected):
    assert _plan_synthesized_range(header, total) == expected


class TestNormalizeUrlCacheKeys:
    """URL variants of the same tracker must canonicalize identically —
    the cache key is sha256(normalized URL), so every variant that doesn't
    is a needless cold parse (and a stale-serving split brain)."""

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            # Google Sheets variants of the same sheet
            ("https://docs.google.com/spreadsheets/d/ABC123/htmlview",
             "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=0"),
            ("https://docs.google.com/spreadsheets/d/ABC123/htmlview",
             "https://docs.google.com/spreadsheets/d/ABC123/edit?usp=sharing"),
            ("https://docs.google.com/spreadsheets/d/ABC123/htmlview",
             "docs.google.com/spreadsheets/d/ABC123/view"),
            # Non-Google host: bare vs trailing slash vs missing scheme
            ("https://yetracker.net/", "https://yetracker.net"),
            ("https://yetracker.net/", "yetracker.net"),
        ],
    )
    def test_variants_share_a_key(self, a, b):
        from src.fetcher import _cache_key, _normalize_url

        assert _cache_key(_normalize_url(a)) == _cache_key(_normalize_url(b))

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("https://docs.google.com/spreadsheets/d/ABC123/htmlview",
             "https://docs.google.com/spreadsheets/d/XYZ789/htmlview"),
            ("https://yetracker.net/", "https://yetracker.net/other"),
        ],
    )
    def test_distinct_resources_get_distinct_keys(self, a, b):
        from src.fetcher import _cache_key, _normalize_url

        assert _cache_key(_normalize_url(a)) != _cache_key(_normalize_url(b))


@pytest.mark.parametrize(
    "header_value,expected",
    [
        # Strong ETags
        ('"abc"', "abc"),
        ('"abc123def"', "abc123def"),
        # Weak ETags (RFC 7232) — both casings
        ('W/"abc"', "abc"),
        ('w/"abc"', "abc"),
        ('W/ "abc"', "abc"),  # tolerate whitespace after W/
        # Unquoted (lenient parsing — some clients drop the quotes)
        ("abc", "abc"),
        # Empty / wildcard / missing
        ("", ""),
        ("*", ""),
        # Surrounding whitespace
        ('  "abc"  ', "abc"),
        ('  W/"abc"  ', "abc"),
        # Multiple entries — take the first
        ('"abc", "def"', "abc"),
        ('W/"abc", "def"', "abc"),
    ],
)
def test_parse_if_none_match(header_value: str, expected: str) -> None:
    assert _parse_if_none_match(header_value) == expected


def test_parse_if_none_match_weak_strong_compare() -> None:
    """A client that sends the weak form must still match the strong tag we issued."""
    issued_strong = "deadbeef"
    client_sends_weak = f'W/"{issued_strong}"'
    client_sends_strong = f'"{issued_strong}"'
    assert _parse_if_none_match(client_sends_weak) == issued_strong
    assert _parse_if_none_match(client_sends_strong) == issued_strong


# ---------------------------------------------------------------------------
# Range slicing for synthesised 206 responses
# ---------------------------------------------------------------------------

from src.api import _slice_byte_stream


async def _chunks(*parts: bytes):
    for p in parts:
        yield p


async def _collect(gen) -> bytes:
    return b"".join([c async for c in gen])


@pytest.mark.asyncio
class TestSliceByteStream:
    """The synthesised-206 slicer must serve exactly bytes [start, end]."""

    async def test_full_range(self):
        out = await _collect(_slice_byte_stream(_chunks(b"hello", b"world"), 0, 9))
        assert out == b"helloworld"

    async def test_range_within_single_chunk(self):
        out = await _collect(_slice_byte_stream(_chunks(b"helloworld"), 2, 6))
        assert out == b"llowo"

    async def test_range_spanning_chunks(self):
        out = await _collect(_slice_byte_stream(_chunks(b"hel", b"low", b"orld"), 2, 7))
        assert out == b"llowor"

    async def test_skips_leading_chunks(self):
        out = await _collect(_slice_byte_stream(_chunks(b"aaa", b"bbb", b"ccc"), 6, 8))
        assert out == b"ccc"

    async def test_stops_after_range_end(self):
        consumed = []

        async def tracking_source():
            for p in (b"aaa", b"bbb", b"ccc"):
                consumed.append(p)
                yield p

        out = await _collect(_slice_byte_stream(tracking_source(), 0, 2))
        assert out == b"aaa"
        assert consumed == [b"aaa"], "must not keep reading past range_end"

    async def test_single_byte(self):
        out = await _collect(_slice_byte_stream(_chunks(b"ab", b"cd"), 2, 2))
        assert out == b"c"

    async def test_range_end_beyond_stream(self):
        """Short upstream: serve what exists, don't raise."""
        out = await _collect(_slice_byte_stream(_chunks(b"abc"), 1, 100))
        assert out == b"bc"

    async def test_empty_chunks_ignored(self):
        out = await _collect(_slice_byte_stream(_chunks(b"", b"abc", b"", b"def"), 1, 4))
        assert out == b"bcde"


# ---------------------------------------------------------------------------
# krakenfiles.com CDN extraction (regression for the page layout as of
# July 2026 — the audio URL sits in an <a>/<source>-adjacent attribute as
# https://{cdn}.krakencloud.net/uploads/{date}/{id}/music.{ext})
# ---------------------------------------------------------------------------

_KRAKEN_PAGE_SNIPPET = """
<div class="lightgallery-wrapper">
  <img src="https://pchs4.krakencloud.net/uploads/01-08-2023/FJmpAhYHMp/waveform.png"/>
</div>
<script>
  new jPlayerPlaylist({jPlayer: "#jquery_jplayer_N"}, [
    {title: "file", m4a: "https://pchs4.krakencloud.net/uploads/01-08-2023/FJmpAhYHMp/music.m4a"}
  ]);
</script>
"""


class TestKrakenResolution:
    def test_cdn_pattern_extracts_audio_url(self):
        from src.streaming import _KRAKEN_CDN_AUDIO_PATTERN

        m = _KRAKEN_CDN_AUDIO_PATTERN.search(_KRAKEN_PAGE_SNIPPET)
        assert m is not None
        assert m.group(0) == (
            "https://pchs4.krakencloud.net/uploads/01-08-2023/FJmpAhYHMp/music.m4a"
        )

    def test_view_url_detected(self):
        from src.streaming import is_kraken_view_url

        assert is_kraken_view_url("https://krakenfiles.com/view/FJmpAhYHMp/file.html")
        assert not is_kraken_view_url("https://krakenfiles.com/somewhere/else")

    def test_resolve_stream_url_passthrough(self):
        from src.streaming import resolve_stream_url

        link = "https://krakenfiles.com/view/FJmpAhYHMp/file.html"
        assert resolve_stream_url(link) == link


# ---------------------------------------------------------------------------
# Artist name inference aliases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected",
    [
        ("Creator, The Tyler Tracker - Google Drive", "Tyler, The Creator"),
        ("The Guy From Degrassi Tracker - Google Drive", "Drake"),
        ("Tyler, The Creator Tracker - Google Drive", "Tyler, The Creator"),
    ],
)
def test_infer_artist_name_aliases(title, expected):
    from src.fetcher import _infer_artist_name

    assert _infer_artist_name(title) == expected
