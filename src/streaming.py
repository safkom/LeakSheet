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

  pixeldrain.com
    https://pixeldrain.com/u/{id}  →  https://pixeldrain.com/api/file/{id}
    (pixeldrain.com/l/{id} is a *list* URL and is intentionally not resolved.)

  drive.google.com
    https://drive.google.com/file/d/{id}/view...
    https://drive.google.com/open?id={id}
    https://drive.google.com/uc?id={id}...
      →  https://drive.google.com/uc?export=download&id={id}
    Large/unscanned files return an HTML virus-scan interstitial instead of
    bytes; the confirm form on that page is parsed and retried once against
    drive.usercontent.google.com/download. See GdriveInterstitialError.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from src.config import USER_AGENT

logger = logging.getLogger(__name__)


# imgur cdnUrl SSRF guard — see docs/decisions.md::streaming.py::imgur-cdnurl-guard
def _ip_is_public(ip_str: str) -> bool:
    """True unless *ip_str* is a private/loopback/link-local/reserved/etc. address."""
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _assert_public_host(host: str, *, source: str) -> None:
    """Raise ValueError unless every address *host* resolves to is public.

    Blocking (socket.getaddrinfo) — call via asyncio.to_thread from async code.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"{source} host does not resolve: {host}") from exc
    for info in infos:
        if not _ip_is_public(info[4][0]):
            raise ValueError(
                f"{source} resolved to non-public address {info[4][0]} for host {host}"
            )


def _assert_public_https_url(url: str, *, source: str) -> None:
    """Raise ValueError unless *url* is https and resolves only to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"{source} returned non-https URL: {url[:80]}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"{source} returned URL with no host: {url[:80]}")
    _assert_public_host(host, source=source)


async def assert_public_redirect_target(resp: httpx.Response, *, source: str) -> None:
    """Re-validate that the FINAL url of a (redirect-followed) response is a
    public https host; aclose the response and raise ValueError otherwise.

    ``follow_redirects=True`` means an allow-listed / pre-validated origin can
    still 30x to an internal address (169.254.169.254, localhost, RFC1918) — the
    exact SSRF class the gdrive path already guards. This closes the same hole
    on the general stream / image-proxy paths. Because callers pass
    ``stream=True`` and run this before reading the body, no internal content is
    ever relayed to the client.
    """
    final = str(resp.url)
    parsed = urlparse(final)
    host = parsed.hostname or ""
    try:
        if parsed.scheme != "https":
            raise ValueError(f"{source} redirected to non-https URL: {final[:80]}")
        await asyncio.to_thread(_assert_public_host, host, source=source)
    except ValueError:
        await resp.aclose()
        raise


class PublicOnlyAsyncTransport(httpx.AsyncHTTPTransport):
    """SSRF guard at the transport layer: before every connection (including
    each redirect hop) reject any host that resolves only-or-partly to a
    non-public address.

    This narrows the DNS-rebinding window — the check runs at connect time, not
    only during pre-flight validation — and defends every request made through
    the shared clients. Exact-IP pinning would fully close the residual rebind
    race but needs live verification against each upstream, so it is deferred;
    ``assert_public_redirect_target`` is the tested belt-and-suspenders on top.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        try:
            is_literal = ipaddress.ip_address(host) is not None
        except ValueError:
            is_literal = False
        try:
            if is_literal:
                if not _ip_is_public(host):
                    raise ValueError(f"blocked non-public literal IP {host}")
            else:
                loop = asyncio.get_running_loop()
                infos = await loop.getaddrinfo(
                    host, request.url.port, type=socket.SOCK_STREAM
                )
                for info in infos:
                    if not _ip_is_public(info[4][0]):
                        raise ValueError(
                            f"blocked non-public address {info[4][0]} for host {host}"
                        )
        except ValueError as exc:
            raise httpx.ConnectError(str(exc), request=request) from exc
        return await super().handle_async_request(request)


# Gzip-bomb cap on scraper reads — see docs/decisions.md::streaming.py::scraper-read-cap
_SCRAPER_READ_CAP = 512 * 1024


async def _get_text_capped(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    cap: int = _SCRAPER_READ_CAP,
) -> tuple[int, str]:
    """GET *url*, decoding at most *cap* decompressed bytes. Returns
    (status_code, text). Stops consuming the body once the cap is reached."""
    request = client.build_request("GET", url, headers=headers)
    resp = await client.send(request, stream=True)
    try:
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) >= cap:
                break
        return resp.status_code, bytes(buf[:cap]).decode("utf-8", errors="ignore")
    finally:
        await resp.aclose()


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

# pixeldrain.com — /u/ is a single file, /l/ is a list (intentionally not
# matched here; multi-file lists are deliberately unsupported).
_PIXELDRAIN_PATTERN = re.compile(
    r"https?://(?:www\.)?pixeldrain\.com/u/([A-Za-z0-9]+)",
)

# gdrive URL forms — see docs/decisions.md::streaming.py::gdrive-url-forms
_GDRIVE_FILE_D_PATTERN = re.compile(
    r"https?://(?:www\.)?drive\.google\.com/file/d/([A-Za-z0-9_-]+)",
)
_GDRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Every host `resolve_stream_url` can emit. The API's stream-proxy allowlist
# is this set, so resolver and allowlist can't drift (they had: four stale
# entries accumulated in the hand-maintained copy).
ALLOWED_STREAM_HOSTS = frozenset({
    "api.pillows.su",     # pillows.su / pillowcase.su both resolve here
    "imgur.gg",           # primary API host (2026-08: temp.imgur.gg now 404s)
    "temp.imgur.gg",      # kept as the resolver's fallback host
    "music.froste.lol",
    "krakenfiles.com",    # view URL passes through; CDN host validated by
                          # _KRAKEN_CDN_AUDIO_PATTERN when resolved lazily
    "pixeldrain.com",
    "drive.google.com",   # uc?export=download form; the usercontent.google.com
                          # confirm retry is validated inside _fetch_gdrive
})

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STREAM_TIMEOUT = 30.0
_STREAM_USER_AGENT = USER_AGENT  # shared backend UA from src.config

# Audio MIME types we accept (reject HTML error pages etc.)
_AUDIO_MIMES = {
    "audio/",
    # Some hosts (imgur.gg) serve audio inside an mp4/webm container and
    # label it video/*. The client plays the audio track either way; this
    # gate exists to reject HTML error pages, not to police containers.
    "video/",
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
            # limits live on the transport because a custom transport bypasses
            # the client-level `limits` argument.
            transport=PublicOnlyAsyncTransport(
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            ),
        )
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared client. Call on application shutdown."""
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None

def _extract_gdrive_id(link: str) -> str | None:
    """Extract a Google Drive file id from any of the supported URL forms.

    Handles ``/file/d/{id}/...``, ``/open?id={id}``, and ``/uc?id={id}...``.
    Returns None if the link isn't a recognised drive.google.com file URL or
    the id contains characters outside [A-Za-z0-9_-].
    """
    m = _GDRIVE_FILE_D_PATTERN.match(link)
    if m:
        file_id = m.group(1)
        return file_id if _GDRIVE_ID_RE.match(file_id) else None

    parsed = urlparse(link)
    host = (parsed.hostname or "").lower()
    if host not in ("drive.google.com", "www.drive.google.com"):
        return None
    if parsed.path not in ("/open", "/uc"):
        return None
    ids = parse_qs(parsed.query).get("id")
    if not ids:
        return None
    file_id = ids[0]
    if not _GDRIVE_ID_RE.match(file_id):
        return None
    return file_id


def resolve_metadata_url(link: str) -> dict[str, str] | None:
    """Convert a file-sharing link to its provider metadata API URL.

    Returns ``{"url": "...", "provider": "pillows"|"froste"|"imgur"|"pixeldrain"}``
    or ``None`` if the host has no metadata API (this includes drive.google.com —
    no metadata provider is implemented for it yet).
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
            "url": f"https://imgur.gg/api/file/{file_id}",
            "provider": "imgur",
        }

    m = _PIXELDRAIN_PATTERN.match(link)
    if m:
        file_id = m.group(1)
        return {
            "url": f"https://pixeldrain.com/api/file/{file_id}/info",
            "provider": "pixeldrain",
        }

    # No metadata API for kraken/gdrive — see docs/decisions.md::streaming.py::no-metadata-hosts
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
        # imgur.gg is the live API host; temp.imgur.gg started 404ing in
        # 2026-08. resolve_imgur_cdn_url still falls back to temp. if this
        # host fails, so a future flip back needs no code change.
        resolved = f"https://imgur.gg/api/file/{file_id}"
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

    m = _PIXELDRAIN_PATTERN.match(link)
    if m:
        file_id = m.group(1)
        resolved = f"https://pixeldrain.com/api/file/{file_id}"
        logger.debug("Resolved pixeldrain.com link %s → %s", link, resolved)
        return resolved

    gdrive_id = _extract_gdrive_id(link)
    if gdrive_id:
        resolved = f"https://drive.google.com/uc?export=download&id={gdrive_id}"
        logger.debug("Resolved drive.google.com link %s → %s", link, resolved)
        return resolved

    # A non-streamable host (YouTube, Instagram, imgbb, …) is normal tracker
    # content, not an anomaly — census/health tooling probes every link, so a
    # WARNING here floods logs. The /stream endpoint still 400s unmatched URLs.
    logger.debug("No stream host matched for link: %s", link)
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
        status, html = await _get_text_capped(
            client,
            view_url,
            {
                "User-Agent": _STREAM_USER_AGENT,
                "Referer": "https://krakenfiles.com/",
            },
        )
        if status != 200:
            raise ValueError(
                f"krakenfiles.com returned {status} for {view_url}"
            )
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
    temp.imgur.gg, retries with temp.imgur.gg. Which of the two hosts works
    has flipped before (temp. was the live one until 2026-08), so both are
    tried rather than hard-coding today's winner.

    Args:
        api_url: e.g. ``https://imgur.gg/api/file/wGLEqSB``

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
            # The cdnUrl is attacker-influenceable — validate the destination
            # is a public https host before the caller streams from it (SSRF).
            await asyncio.to_thread(
                _assert_public_https_url, cdn_url, source="imgur.gg cdnUrl"
            )
            return cdn_url
        except httpx.HTTPError as exc:
            last_err = ValueError(f"imgur.gg API request failed: {exc}")
            continue

    raise last_err  # type: ignore[misc]


# Virus-scan interstitial bypass — see docs/decisions.md::streaming.py::gdrive-interstitial-bypass
_GDRIVE_ALLOWED_HOSTS = {"drive.google.com", "drive.usercontent.google.com"}
_GDRIVE_USERCONTENT_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.googleusercontent\.com$")


class GdriveInterstitialError(Exception):
    """Raised when Google Drive returns an HTML virus-scan interstitial that
    could not be bypassed via the confirm-form retry."""


# Hidden <input> tags anywhere in the confirm page, attribute order agnostic.
_GDRIVE_INPUT_TAG_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_GDRIVE_INPUT_NAME_RE = re.compile(r'name=["\']([^"\']*)["\']', re.IGNORECASE)
_GDRIVE_INPUT_VALUE_RE = re.compile(r'value=["\']([^"\']*)["\']', re.IGNORECASE)
_GDRIVE_INPUT_HIDDEN_RE = re.compile(r'type=["\']hidden["\']', re.IGNORECASE)


def parse_gdrive_confirm_form(html: str) -> dict[str, str] | None:
    """Extract hidden form fields from Google Drive's virus-scan interstitial.

    Returns a dict of the hidden ``<input>`` name/value pairs (typically
    ``id``, ``export``, ``confirm``, ``uuid``), or None if the page doesn't
    contain a recognisable confirm form (no hidden ``id``/``confirm`` pair).
    """
    fields: dict[str, str] = {}
    for tag in _GDRIVE_INPUT_TAG_RE.findall(html):
        if not _GDRIVE_INPUT_HIDDEN_RE.search(tag):
            continue
        name_m = _GDRIVE_INPUT_NAME_RE.search(tag)
        if not name_m:
            continue
        value_m = _GDRIVE_INPUT_VALUE_RE.search(tag)
        fields[name_m.group(1)] = value_m.group(1) if value_m else ""

    if "id" not in fields or "confirm" not in fields:
        return None
    return fields


def build_gdrive_confirm_url(fields: dict[str, str]) -> str:
    """Build the drive.usercontent.google.com/download retry URL."""
    return f"https://drive.usercontent.google.com/download?{urlencode(fields)}"


def is_gdrive_stream_url(url: str) -> bool:
    """Return True if *url* is the drive.google.com stream URL produced by
    ``resolve_stream_url`` (used to dispatch into the gdrive fetch path)."""
    try:
        return (urlparse(url).hostname or "").lower() == "drive.google.com"
    except Exception:
        return False


def _is_gdrive_host_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in _GDRIVE_ALLOWED_HOSTS or bool(_GDRIVE_USERCONTENT_RE.match(host))


async def _fetch_gdrive(stream_url: str, headers: dict[str, str]) -> httpx.Response:
    """Fetch a Google Drive stream URL, transparently bypassing the
    virus-scan interstitial once via the confirm-form retry.

    Returns the final upstream streaming response (caller must aclose it).
    Raises GdriveInterstitialError if HTML persists after the retry, or
    ValueError if a request would target a host outside the fixed allowlist.
    """
    client = _get_shared_client()

    async def _get(url: str) -> httpx.Response:
        if not _is_gdrive_host_allowed(url):
            raise ValueError(f"gdrive request targets disallowed host: {url[:80]}")
        request = client.build_request("GET", url, headers=headers)
        resp = await client.send(request, stream=True)
        if not _is_gdrive_host_allowed(str(resp.url)):
            await resp.aclose()
            raise ValueError(
                f"gdrive request redirected off-allowlist to {str(resp.url)[:80]}"
            )
        return resp

    resp = await _get(stream_url)

    # Permission-required/private files: pass through untouched so the
    # caller can relay the 403 as-is rather than treating it as an
    # interstitial or a generic upstream error.
    if resp.status_code == 403:
        return resp

    ct = resp.headers.get("content-type", "")
    base_ct = ct.split(";")[0].strip().lower()
    if resp.status_code == 200 and base_ct == "text/html":
        # Cap the interstitial read — the confirm form is always near the top,
        # and an uncapped decompressed read of a crafted page could OOM.
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) >= _SCRAPER_READ_CAP:
                break
        await resp.aclose()
        fields = parse_gdrive_confirm_form(
            bytes(buf[:_SCRAPER_READ_CAP]).decode("utf-8", errors="ignore")
        )
        if not fields:
            raise GdriveInterstitialError(
                "drive.google.com returned HTML with no recognisable confirm form"
            )
        confirm_url = build_gdrive_confirm_url(fields)
        resp = await _get(confirm_url)
        if resp.status_code == 403:
            return resp
        retry_ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if retry_ct == "text/html":
            await resp.aclose()
            raise GdriveInterstitialError(
                "drive.google.com interstitial persisted after confirm retry"
            )

    return resp


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

    # gdrive dedicated path — see docs/decisions.md::streaming.py::gdrive-interstitial-bypass
    if is_gdrive_stream_url(stream_url):
        resp = await _fetch_gdrive(stream_url, req_headers)
        try:
            if resp.status_code == 403:
                return resp
            if resp.status_code not in (200, 206, 416):
                logger.error("Upstream %s returned HTTP %s", stream_url, resp.status_code)
                raise ValueError(f"Upstream returned {resp.status_code}")
            ct = resp.headers.get("content-type", "")
            if resp.status_code != 416 and ct and not _is_audio_content_type(ct):
                logger.warning("Upstream %s returned non-media content-type: %s", stream_url, ct)
                raise ValueError(f"Upstream returned non-audio content: {ct}")
        except Exception:
            await resp.aclose()
            raise
        return resp

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

    # follow_redirects=True can land us on an internal host even when the
    # resolved stream_url was public/allow-listed (SSRF). Re-validate the final
    # url before relaying any bytes — mirrors the gdrive path's re-check.
    await assert_public_redirect_target(resp, source="stream upstream")

    try:
        ct = resp.headers.get("content-type", "")
        # 416 passes through so the API layer can relay it as a real 416
        # (Range Not Satisfiable) instead of a generic upstream error.
        if resp.status_code not in (200, 206, 416):
            logger.error("Upstream %s returned HTTP %s", stream_url, resp.status_code)
            raise ValueError(f"Upstream returned {resp.status_code}")

        if resp.status_code != 416 and ct and not _is_audio_content_type(ct):
            logger.warning("Upstream %s returned non-audio content-type: %s", stream_url, ct)
            raise ValueError(f"Upstream returned non-audio content: {ct}")
    except Exception:
        await resp.aclose()
        raise

    return resp
