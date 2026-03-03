"""LeakSheet — Streaming URL resolution and audio proxying.

Transforms file-sharing links from tracker spreadsheets into
direct audio stream URLs.  Supported hosts:

  pillows.su / pillowcase.su
    https://pillows.su/f/{id}  →  https://api.pillows.su/api/get/{id}

  imgur.gg / temp.imgur.gg
    https://temp.imgur.gg/f/{id}  →  fetch /api/file/{id} JSON  →  cdnUrl
    https://imgur.gg/f/{id}       →  fetch /api/file/{id} JSON  →  cdnUrl

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

# ---------------------------------------------------------------------------
# Constants
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

def resolve_stream_url(link: str) -> str | None:
    """Convert a file-sharing link to a direct audio stream URL.

    Returns the API URL if the link matches a known host, else None.
    For imgur.gg, returns the metadata API URL (caller must resolve CDN via
    ``resolve_imgur_cdn_url``).
    """
    m = _PILLOWS_PATTERN.match(link)
    if m:
        file_id = m.group(2)
        # Both pillows.su and pillowcase.su use api.pillows.su
        return f"https://api.pillows.su/api/get/{file_id}"

    m = _IMGUR_PATTERN.match(link)
    if m:
        file_id = m.group(2)
        # Always use temp.imgur.gg — imgur.gg API returns 404
        return f"https://temp.imgur.gg/api/file/{file_id}"

    m = _FROSTE_PATTERN.match(link)
    if m:
        song_hash = m.group(1)
        return f"https://music.froste.lol/song/{song_hash}/download"

    return None


# ---------------------------------------------------------------------------
# imgur.gg CDN URL resolution
# ---------------------------------------------------------------------------

_IMGUR_API_PATTERN = re.compile(
    r"https?://(?:www\.)?((?:temp\.)?imgur\.gg)/api/file/([A-Za-z0-9_-]+)$",
)


def is_imgur_api_url(url: str) -> bool:
    """Return True if *url* is an imgur.gg metadata API endpoint."""
    return _IMGUR_API_PATTERN.match(url) is not None


async def resolve_imgur_cdn_url(api_url: str) -> str:
    """Fetch imgur.gg file metadata and return the CDN stream URL.

    Tries the given URL first; if it fails and the domain isn't already
    temp.imgur.gg, retries with temp.imgur.gg (the only domain whose
    API reliably works).

    Args:
        api_url: e.g. ``https://temp.imgur.gg/api/file/wGLEqSB``

    Returns:
        The ``cdnUrl`` from the JSON response.

    Raises ValueError on network or API errors.
    """
    urls_to_try = [api_url]
    # If the URL uses imgur.gg (not temp.), queue temp.imgur.gg as fallback
    if "://imgur.gg/" in api_url or "://www.imgur.gg/" in api_url:
        fallback = api_url.replace("://imgur.gg/", "://temp.imgur.gg/").replace(
            "://www.imgur.gg/", "://temp.imgur.gg/"
        )
        urls_to_try.append(fallback)

    last_err: Exception | None = None
    for url in urls_to_try:
        try:
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": _STREAM_USER_AGENT},
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    last_err = ValueError(
                        f"imgur.gg API returned {resp.status_code} for {url}"
                    )
                    continue
                data = resp.json()
                cdn_url = data.get("cdnUrl")
                if not cdn_url:
                    last_err = ValueError(
                        f"imgur.gg API response missing cdnUrl: {url}"
                    )
                    continue
                return cdn_url
        except httpx.HTTPError as exc:
            last_err = ValueError(f"imgur.gg API request failed: {exc}")
            continue

    raise last_err  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Proxy streaming — fetches audio from upstream and yields chunks
# ---------------------------------------------------------------------------


def _is_audio_content_type(ct: str) -> bool:
    """Return True if content-type looks like audio or binary."""
    ct = ct.lower()
    return any(ct.startswith(m) for m in _AUDIO_MIMES)


async def stream_audio(
    stream_url: str, *, range_header: str | None = None
) -> tuple[httpx.Response, httpx.AsyncClient]:
    """Open a streaming connection to the resolved audio URL.

    For imgur.gg metadata URLs, first resolves the CDN URL via the API,
    then streams from the CDN.

    Args:
        stream_url: The resolved API URL to stream from.
        range_header: Optional HTTP Range header to forward (e.g. "bytes=0-1024").

    Returns (response, client) tuple. Caller is responsible for closing both.

    Raises ValueError if upstream returns non-audio content.
    """
    # imgur.gg: resolve metadata API → CDN URL first
    if is_imgur_api_url(stream_url):
        stream_url = await resolve_imgur_cdn_url(stream_url)

    req_headers = {"User-Agent": _STREAM_USER_AGENT}
    if range_header:
        req_headers["Range"] = range_header

    # music.froste.lol requires a Referer header
    if "music.froste.lol/song/" in stream_url:
        song_page = stream_url.removesuffix("/download")
        req_headers["Referer"] = song_page

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(_STREAM_TIMEOUT, read=120.0),
        headers=req_headers,
    )

    request = client.build_request("GET", stream_url)
    resp = await client.send(request, stream=True)

    try:
        ct = resp.headers.get("content-type", "")
        if resp.status_code not in (200, 206):
            raise ValueError(f"Upstream returned {resp.status_code}")

        if ct and not _is_audio_content_type(ct):
            raise ValueError(f"Upstream returned non-audio content: {ct}")
    except Exception:
        await resp.aclose()
        await client.aclose()
        raise

    return resp, client
