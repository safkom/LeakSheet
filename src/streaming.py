"""LeakSheet — Streaming URL resolution and audio proxying.

Transforms file-sharing links from tracker spreadsheets into
direct audio stream URLs.  Supported hosts:

  pillows.su / pillowcase.su
    https://pillows.su/f/{id}  →  https://api.pillows.su/api/get/{id}

  imgur.gg / temp.imgur.gg
    https://temp.imgur.gg/f/{id}  →  https://temp.imgur.gg/api/file/{id}/download
    https://imgur.gg/f/{id}       →  https://imgur.gg/api/file/{id}/download

  music.froste.lol
    https://music.froste.lol/song/{hash}  →  https://music.froste.lol/song/{hash}/download
"""

from __future__ import annotations

import re

import httpx


# ---------------------------------------------------------------------------
# URL patterns — order matters (most specific first)
# ---------------------------------------------------------------------------

# pillows.su / pillowcase.su
_PILLOWS_PATTERN = re.compile(
    r"https?://(?:www\.)?(pillows\.su|pillowcase\.su)/f/([A-Za-z0-9_-]+)",
)

# imgur.gg / temp.imgur.gg
_IMGUR_PATTERN = re.compile(
    r"https?://(?:www\.)?((?:temp\.)?imgur\.gg)/f/([A-Za-z0-9_-]+)",
)
# music.froste.lol
_FROSTE_PATTERN = re.compile(
    r"https?://music\.froste\.lol/song/([a-f0-9]+)",
)

def resolve_stream_url(link: str) -> str | None:
    """Convert a file-sharing link to a direct audio stream URL.

    Returns the API URL if the link matches a known host, else None.
    """
    m = _PILLOWS_PATTERN.match(link)
    if m:
        file_id = m.group(2)
        # Both pillows.su and pillowcase.su use api.pillows.su
        return f"https://api.pillows.su/api/get/{file_id}"

    m = _IMGUR_PATTERN.match(link)
    if m:
        domain = m.group(1)  # "imgur.gg" or "temp.imgur.gg"
        file_id = m.group(2)
        return f"https://{domain}/api/file/{file_id}/download"

    m = _FROSTE_PATTERN.match(link)
    if m:
        song_hash = m.group(1)
        return f"https://music.froste.lol/song/{song_hash}/download"

    return None


# ---------------------------------------------------------------------------
# Proxy streaming — fetches audio from upstream and yields chunks
# ---------------------------------------------------------------------------

_STREAM_TIMEOUT = 30.0
_STREAM_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LeakSheet/1.0"

# Audio MIME types we accept (reject HTML error pages etc.)
_AUDIO_MIMES = {
    "audio/",
    "application/octet-stream",
    "application/ogg",
    "binary/octet-stream",
}


def _is_audio_content_type(ct: str) -> bool:
    """Return True if content-type looks like audio or binary."""
    ct = ct.lower()
    return any(ct.startswith(m) for m in _AUDIO_MIMES)


def stream_audio(
    stream_url: str, *, range_header: str | None = None
) -> tuple[httpx.Response, httpx.Client]:
    """Open a streaming connection to the resolved audio URL.

    Args:
        stream_url: The resolved API URL to stream from.
        range_header: Optional HTTP Range header to forward (e.g. "bytes=0-1024").

    Returns (response, client) tuple. Caller is responsible for closing both.

    Raises ValueError if upstream returns non-audio content.
    """
    req_headers = {"User-Agent": _STREAM_USER_AGENT}
    if range_header:
        req_headers["Range"] = range_header

    # music.froste.lol requires a Referer header
    if "music.froste.lol/song/" in stream_url:
        song_page = stream_url.removesuffix("/download")
        req_headers["Referer"] = song_page

    client = httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(_STREAM_TIMEOUT, read=120.0),
        headers=req_headers,
    )

    request = client.build_request("GET", stream_url)
    resp = client.send(request, stream=True)

    try:
        ct = resp.headers.get("content-type", "")
        if resp.status_code not in (200, 206):
            raise ValueError(f"Upstream returned {resp.status_code}")

        if ct and not _is_audio_content_type(ct):
            raise ValueError(f"Upstream returned non-audio content: {ct}")
    except Exception:
        resp.close()
        client.close()
        raise

    return resp, client
