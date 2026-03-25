"""LeakSheet — Streaming URL resolution and audio proxying.

Transforms file-sharing links from tracker spreadsheets into
direct audio stream URLs.  Supported hosts:

  pillows.su / pillowcase.su
    https://pillows.su/f/{id}  →  https://api.pillows.su/api/get/{id}

  imgur.gg / temp.imgur.gg
    https://temp.imgur.gg/f/{id}  →  fetch /api/file/{id} JSON  →  cdnUrl
    https://imgur.gg/f/{id}       →  fetch /api/file/{id} JSON  →  cdnUrl

  music.froste.lol
    https://music.froste.lol/song/{hash}  →  https://music.froste.lol/song/{hash}/file

  krakenfiles.com
    https://krakenfiles.com/view/{id}/file.html  →  fetch page HTML  →  krakencloud.net CDN URL
    Requires Referer: https://krakenfiles.com/ when streaming from CDN.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)


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

# krakenfiles.com
_KRAKEN_PATTERN = re.compile(
    r"https?://(?:www\.)?krakenfiles\.com/view/([A-Za-z0-9_-]+)/file\.html",
)

# krakencloud.net CDN audio URLs (used internally for validation only)
_KRAKEN_CDN_AUDIO_PATTERN = re.compile(
    r"https://[a-z0-9]+\.krakencloud\.net/uploads/[^\s\"'<>]+"
    r"/music\.(?:m4a|mp3|ogg|flac|wav|aac)",
    re.IGNORECASE,
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

# ---------------------------------------------------------------------------
# Shared httpx client — connection pooling across all stream requests.
# ---------------------------------------------------------------------------

_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """Return (and lazily create) a shared async HTTP client for streaming."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(_STREAM_TIMEOUT, read=120.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared client. Call on application shutdown."""
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None

def resolve_metadata_url(link: str) -> dict[str, str] | None:
    """Convert a file-sharing link to its provider metadata API URL.

    Returns ``{"url": "...", "provider": "pillows"|"froste"|"imgur"}``
    or ``None`` if the host has no metadata API.
    """
    m = _PILLOWS_PATTERN.match(link)
    if m:
        file_id = m.group(2)
        return {
            "url": f"https://api.pillows.su/api/metadata/{file_id}.txt",
            "provider": "pillows",
        }

    m = _FROSTE_PATTERN.match(link)
    if m:
        song_hash = m.group(1)
        return {
            "url": f"https://music.froste.lol/song/{song_hash}/analyze-quality",
            "provider": "froste",
        }

    m = _IMGUR_PATTERN.match(link)
    if m:
        file_id = m.group(2)
        return {
            "url": f"https://temp.imgur.gg/api/file/{file_id}",
            "provider": "imgur",
        }

    return None


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
        resolved = f"https://api.pillows.su/api/get/{file_id}"
        logger.debug("Resolved pillows.su link %s → %s", link, resolved)
        return resolved

    m = _IMGUR_PATTERN.match(link)
    if m:
        file_id = m.group(2)
        # Always use temp.imgur.gg — imgur.gg API returns 404
        resolved = f"https://temp.imgur.gg/api/file/{file_id}"
        logger.debug("Resolved imgur.gg link %s → metadata API %s", link, resolved)
        return resolved

    m = _FROSTE_PATTERN.match(link)
    if m:
        song_hash = m.group(1)
        resolved = f"https://music.froste.lol/song/{song_hash}/file"
        logger.debug("Resolved froste.lol link %s → %s", link, resolved)
        return resolved

    m = _KRAKEN_PATTERN.match(link)
    if m:
        # Return view URL unchanged — resolved to CDN URL lazily in stream_audio()
        logger.debug("Resolved krakenfiles.com link %s (CDN resolved lazily)", link)
        return link

    logger.warning("No stream host matched for link: %s", link)
    return None


# ---------------------------------------------------------------------------
# krakenfiles.com CDN URL resolution
# ---------------------------------------------------------------------------

def is_kraken_view_url(url: str) -> bool:
    """Return True if *url* is a krakenfiles.com view page URL."""
    return bool(_KRAKEN_PATTERN.match(url))


async def resolve_kraken_cdn_url(view_url: str) -> str:
    """Fetch krakenfiles.com view page and return the CDN audio stream URL.

    The audio URL is embedded directly in the page HTML and always follows
    the pattern: https://{cdn}.krakencloud.net/uploads/{date}/{id}/music.{ext}

    Args:
        view_url: e.g. ``https://krakenfiles.com/view/WS7wzkrklJ/file.html``

    Returns:
        Direct CDN audio URL (krakencloud.net).

    Raises ValueError if the page cannot be fetched or no audio URL is found.
    """
    client = _get_shared_client()
    try:
        resp = await client.get(
            view_url,
            headers={
                "User-Agent": _STREAM_USER_AGENT,
                "Referer": "https://krakenfiles.com/",
            },
        )
        if resp.status_code != 200:
            raise ValueError(
                f"krakenfiles.com returned {resp.status_code} for {view_url}"
            )
        html = resp.text
    except httpx.HTTPError as exc:
        raise ValueError(f"krakenfiles.com fetch failed: {exc}") from exc

    m = _KRAKEN_CDN_AUDIO_PATTERN.search(html)
    if not m:
        raise ValueError(f"No audio URL found in krakenfiles.com page: {view_url}")
    return m.group(0)


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
            client = _get_shared_client()
            resp = await client.get(
                url, headers={"User-Agent": _STREAM_USER_AGENT}
            )
            if resp.status_code != 200:
                last_err = ValueError(
                    f"imgur.gg API returned {resp.status_code} for {url}"
                )
                continue
            try:
                data = resp.json()
            except ValueError as exc:
                logger.warning("imgur API returned non-JSON response (status %s): %s", resp.status_code, exc)
                last_err = ValueError(f"imgur API non-JSON response: {exc}")
                continue
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
) -> httpx.Response:
    """Open a streaming connection to the resolved audio URL.

    For imgur.gg metadata URLs, first resolves the CDN URL via the API,
    then streams from the CDN.

    Args:
        stream_url: The resolved API URL to stream from.
        range_header: Optional HTTP Range header to forward (e.g. "bytes=0-1024").

    Returns the streaming response. Caller is responsible for closing it
    with ``await resp.aclose()``.

    Raises ValueError if upstream returns non-audio content.
    """
    # imgur.gg: resolve metadata API → CDN URL first
    if is_imgur_api_url(stream_url):
        stream_url = await resolve_imgur_cdn_url(stream_url)

    # krakenfiles.com: fetch view page to extract CDN URL
    if is_kraken_view_url(stream_url):
        stream_url = await resolve_kraken_cdn_url(stream_url)

    req_headers = {"User-Agent": _STREAM_USER_AGENT}
    if range_header:
        req_headers["Range"] = range_header

    # music.froste.lol requires a Referer header
    if "music.froste.lol/song/" in stream_url:
        song_page = stream_url.removesuffix("/download")
        req_headers["Referer"] = song_page

    # krakencloud.net requires Referer: https://krakenfiles.com/
    if "krakencloud.net" in stream_url:
        req_headers["Referer"] = "https://krakenfiles.com/"

    client = _get_shared_client()

    request = client.build_request("GET", stream_url, headers=req_headers)
    resp = await client.send(request, stream=True)

    try:
        ct = resp.headers.get("content-type", "")
        if resp.status_code not in (200, 206):
            logger.error("Upstream %s returned HTTP %s", stream_url, resp.status_code)
            raise ValueError(f"Upstream returned {resp.status_code}")

        if ct and not _is_audio_content_type(ct):
            logger.warning("Upstream %s returned non-audio content-type: %s", stream_url, ct)
            raise ValueError(f"Upstream returned non-audio content: {ct}")
    except Exception:
        await resp.aclose()
        raise

    return resp
