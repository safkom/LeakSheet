"""LeakSheet — Streaming URL resolution and audio proxying.

Transforms file-sharing links from tracker spreadsheets into
direct audio stream URLs.  Supported hosts:

  pillows.su / pillowcase.su
    https://pillows.su/f/{id}  →  https://api.pillows.su/api/get/{id}

  imgur.gg / temp.imgur.gg
    https://temp.imgur.gg/f/{id}  →  https://temp.imgur.gg/api/file/{id}/download
    https://imgur.gg/f/{id}       →  https://imgur.gg/api/file/{id}/download
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

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

    return None


def find_streamable_link(links: list[str]) -> tuple[str | None, str | None]:
    """Find the first streamable link from a list and return (original, stream_url).

    Returns (None, None) if no links are streamable.
    """
    for link in links:
        stream = resolve_stream_url(link)
        if stream is not None:
            return link, stream
    return None, None


def is_streamable(links: list[str]) -> bool:
    """Check whether any link in the list can be streamed."""
    return any(resolve_stream_url(lnk) is not None for lnk in links)


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


def stream_audio(stream_url: str) -> httpx.Response:
    """Open a streaming connection to the resolved audio URL.

    Returns the httpx.Response with stream=True.
    Caller is responsible for closing.

    Raises ValueError if upstream returns non-audio content.
    """
    client = httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(_STREAM_TIMEOUT, read=120.0),
        headers={"User-Agent": _STREAM_USER_AGENT},
    )

    resp = client.stream("GET", stream_url).__enter__()

    ct = resp.headers.get("content-type", "")
    if resp.status_code != 200:
        resp.close()
        client.close()
        raise ValueError(f"Upstream returned {resp.status_code}")

    if ct and not _is_audio_content_type(ct):
        resp.close()
        client.close()
        raise ValueError(f"Upstream returned non-audio content: {ct}")

    # Attach client to response so caller can close both
    resp._client = client  # type: ignore[attr-defined]
    return resp
