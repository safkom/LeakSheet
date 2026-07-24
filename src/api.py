"""LeakSheet — FastAPI HTTP layer.

Endpoints:
  POST /sheet       — send a tracker URL, get parsed Artist JSON back
                      (ETag / stale-while-revalidate)
  GET  /trackers    — TrackerHub discovery list, best-first
  GET  /stream      — proxy audio/video from supported file hosts (Range support)
  GET  /image-proxy — proxy images through backend (width buckets, disk cache)
  GET  /metadata    — file metadata from provider APIs (incl. media_kind)
  POST /cache/clear — clear the URL fetch cache (admin: X-Admin-Token)

Note: In production (DO App Platform), these are served under /api/* via
ingress routing.  The /api prefix is stripped by the platform before reaching
this app.  In local dev, Vite's proxy rewrites /api/* → /* when forwarding.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import StreamingResponse

from src.config import USER_AGENT
from src.fetcher import (
    AccessDeniedError,
    CACHE_DIR,
    async_fetch_and_parse,
    async_get_cached_age,
    async_get_cached_etag,
    async_get_cached_parsed_bytes,
    clear_cache,
    compute_content_hash,
    DEFAULT_CACHE_TTL,
    InvalidURLError,
    NetworkError,
    NoTablesError,
    ParseError,
    PhaseTimer,
    STALE_CACHE_TTL,
    stale_parsed_cache_urls,
)
from src.streaming import (
    ALLOWED_STREAM_HOSTS,
    GdriveInterstitialError,
    PublicOnlyAsyncTransport,
    close_shared_client,
    resolve_metadata_url,
    resolve_stream_url,
    stream_audio,
    _get_shared_client,
)


# ---------------------------------------------------------------------------
# MIME type corrections — upstream hosts sometimes send non-standard types
# that iOS Safari / WebKit rejects as "source not supported".
# ---------------------------------------------------------------------------

_MIME_CORRECTIONS: dict[str, str] = {
    # audio/m4a, audio/x-m4a are not registered IANA types; Safari needs audio/mp4
    "audio/m4a": "audio/mp4",
    "audio/m4b": "audio/mp4",
    "audio/x-m4a": "audio/mp4",
}

# ---------------------------------------------------------------------------
# Audio format sniffing — magic-byte detection of actual container format.
# Some file hosts (e.g. pillows.su) always report "audio/mp4" regardless of
# the actual format.  Safari strictly validates Content-Type against the
# actual data; Chrome is lenient.  We peek at the first bytes to fix the type.
# ---------------------------------------------------------------------------

def _sniff_audio_format(header: bytes) -> str | None:
    """Detect audio format from magic bytes.  Returns corrected MIME or None."""
    if not header:
        return None

    # Ogg container (Vorbis, Opus, FLAC-in-Ogg) — "OggS"
    if header[:4] == b"OggS":
        return "audio/ogg"
    # Partial Ogg: a short read (e.g. Safari's bytes=0-1 probe) that is a
    # genuine prefix of the "OggS" signature — not just any byte starting 'O',
    # which would misclassify tiny non-Ogg bodies.
    if 0 < len(header) < 4 and b"OggS".startswith(header):
        return "audio/ogg"

    # FLAC — "fLaC"
    if header[:4] == b"fLaC":
        return "audio/flac"

    # WAV — "RIFF....WAVE"
    if header[:4] == b"RIFF" and (len(header) < 12 or header[8:12] == b"WAVE"):
        return "audio/wav"

    # MP3 — ID3 tag header
    if header[:3] == b"ID3":
        return "audio/mpeg"

    # MP3 — raw sync frame (0xFF 0xEx or 0xFF 0xFx)
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return "audio/mpeg"

    # MP4 / M4A — standard ftyp box at offset 4
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return "audio/mp4"

    # Other MP4 boxes at offset 4 (moov, mdat, free, skip, wide)
    if len(header) >= 8 and header[4:8] in _MP4_BOXES:
        return "audio/mp4"

    return None

_MP4_BOXES = {b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot"}

# Map file extensions to MIME types — used to resolve generic upstream types
# (application/octet-stream) when the URL contains a recognisable extension.
_EXT_TO_MIME: dict[str, str] = {
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
}

# Map corrected MIME types to file extensions for Content-Disposition
_MIME_TO_EXT: dict[str, str] = {
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/flac": ".flac",
    "audio/aac": ".aac",
    "audio/x-m4a": ".m4a",
}


_CD_FILENAME_RE = re.compile(
    r'filename\*?=(?:UTF-8\'\')?["\']?([^;\n"\']+)', re.IGNORECASE
)


def _ext_from_content_disposition(cd: str) -> str:
    """Extract file extension from a Content-Disposition header value."""
    m = _CD_FILENAME_RE.search(cd)
    if m:
        from posixpath import splitext
        _, ext = splitext(m.group(1).strip())
        return ext.lower()
    return ""


def _fix_audio_mime(
    ct: str | None,
    url: str | None = None,
    content_disposition: str | None = None,
) -> str:
    """Return a corrected MIME type suitable for browser <audio> playback.

    Resolution order for generic binary types (application/octet-stream etc.):
    1. Content-Disposition filename extension (most reliable — file hosts always
       include the real filename even when the URL path has no extension, e.g.
       api.pillows.su/api/get/{id} serves m4a directly with no redirect).
    2. URL path extension (works when upstream redirects to a CDN URL with ext).
    3. Fall back to audio/mpeg.

    This is critical for Safari, which strictly validates Content-Type and
    rejects m4a data served as audio/mpeg with "Source not supported".
    """
    if not ct:
        base = ""
    else:
        # Strip parameters (e.g. "; charset=utf-8")
        base = ct.split(";")[0].strip().lower()

    # Apply explicit corrections first (non-standard but unambiguous types)
    if base in _MIME_CORRECTIONS:
        return _MIME_CORRECTIONS[base]

    # For generic binary types, try to determine the real format.
    if base in ("application/octet-stream", "binary/octet-stream", ""):
        # 1. Content-Disposition filename (e.g. 'attachment; filename="track.m4a"')
        if content_disposition:
            ext = _ext_from_content_disposition(content_disposition)
            if ext in _EXT_TO_MIME:
                return _EXT_TO_MIME[ext]

        # 2. URL path extension (works when upstream redirects to CDN URL)
        if url:
            from urllib.parse import urlparse
            from posixpath import splitext
            path = urlparse(url).path
            ext = splitext(path)[1].lower()
            if ext in _EXT_TO_MIME:
                return _EXT_TO_MIME[ext]

        # Unknown format — fall back to a safe generic
        return "audio/mpeg"

    return base


# ---------------------------------------------------------------------------
# Client-side Cache-Control policies, one per endpoint family
# ---------------------------------------------------------------------------

_CC_SHEET = "public, max-age=300"       # /sheet — short; SWR handles freshness
_CC_IMAGE = "public, max-age=86400"     # /image-proxy — immutable art, 1 day
_CC_METADATA = "public, max-age=3600"   # /metadata + /trackers — hourly TTL caches
_CC_TRACKERS_STALE = "public, max-age=600"  # /trackers stale fallback — retry sooner


# ---------------------------------------------------------------------------
# SSRF protection — domain allowlists for proxy endpoints
# ---------------------------------------------------------------------------

_IMAGE_ALLOWED_DOMAINS = {
    # Exact hostnames allowed for image proxy
    "lh3.googleusercontent.com",
    "lh4.googleusercontent.com",
    "lh5.googleusercontent.com",
    "lh6.googleusercontent.com",
    "lh7-rt.googleusercontent.com",
    "ggpht.com",
    "gstatic.com",
}

# Subdomains of these are also allowed (e.g. lh3.googleusercontent.com)
_IMAGE_ALLOWED_PARENT_DOMAINS = {
    "googleusercontent.com",
    "ggpht.com",
    "gstatic.com",
    "google.com",
}

# Single source of truth: the hosts resolve_stream_url can emit.
_STREAM_ALLOWED_DOMAINS = ALLOWED_STREAM_HOSTS


def _is_allowed_domain(url: str, allowed: set[str], parent_domains: set[str] | None = None) -> bool:
    """Check if the URL's hostname is in the explicit allow-list.

    Exact match first. If parent_domains is provided, also accepts any hostname
    that is a direct or nested subdomain of one of those parent domains.
    """
    from urllib.parse import urlparse
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        if hostname in allowed:
            return True
        if parent_domains:
            return any(hostname == d or hostname.endswith("." + d) for d in parent_domains)
        return False
    except Exception as e:
        logger.debug("URL domain check failed for %s: %s", url[:80], e)
        return False


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

# Lazily-initialized HTTP client for proxy endpoints
_proxy_client: httpx.AsyncClient | None = None


def _get_proxy_client() -> httpx.AsyncClient:
    """Return shared httpx client, creating (or re-creating) as needed."""
    global _proxy_client
    if _proxy_client is None or _proxy_client.is_closed:
        _proxy_client = httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            # SSRF guard: reject connecting to a non-public host on any hop, so
            # an allow-listed image URL that 30x-redirects to an internal
            # address (169.254.169.254, localhost, RFC1918) is refused at
            # connect rather than proxied back.
            transport=PublicOnlyAsyncTransport(),
            headers={
                # Deliberately browser-like (not the shared LeakSheet UA):
                # Google image CDNs vary caching/format behavior by UA.
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
    return _proxy_client


class _StreamSafeGZipMiddleware(GZipMiddleware):
    """GZipMiddleware that skips compression for the /stream audio proxy endpoint.

    GZip compression on streaming audio responses removes Content-Length
    (gzip can't know the compressed size upfront for a streaming body), which
    causes audio.duration to become Infinity on iOS Safari and makes Range-based
    seeking completely broken — byte offsets in Range headers refer to the raw
    audio stream, not the gzip-compressed one.
    """

    # /image-proxy is skipped too: image bytes are already compressed, so
    # gzip only burns CPU and delays time-to-first-byte.
    _GZIP_EXEMPT_PATHS = {"/stream", "/image-proxy"}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").rstrip("/") in self._GZIP_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Prewarm loop (2026-07-20 review): frequently-updated trackers otherwise
    # always serve stale-first once per TTL window. Disable with
    # LEAKSHEET_PREWARM=0. The loop sleeps BEFORE its first pass, so startup
    # (and TestClient contexts) never fire network work.
    prewarm_task: asyncio.Task | None = None
    if os.environ.get("LEAKSHEET_PREWARM", "1") != "0":
        prewarm_task = asyncio.create_task(_prewarm_loop())
    yield
    # Shutdown: stop background work and close both shared HTTP clients.
    if prewarm_task is not None:
        prewarm_task.cancel()
        try:
            await prewarm_task
        except asyncio.CancelledError:
            pass
    if _proxy_client is not None:
        await _proxy_client.aclose()
    await close_shared_client()


app = FastAPI(
    title="LeakSheet",
    description="Parser + API for Google Spreadsheet-based music tracker documents",
    version="0.3.0",
    lifespan=lifespan,
)

# compresslevel 6 ≈ level 9's ratio on JSON at a fraction of the CPU —
# level 9 spent ~0.5s gzipping a 6.5MB artist on every warm request.
app.add_middleware(_StreamSafeGZipMiddleware, minimum_size=1000, compresslevel=6)


# Expensive endpoints worth throttling: cold sheet fetches and the upstream
# proxies. Cheap/cached endpoints (/trackers) are left alone.
_RATE_LIMIT_PATHS = ("/sheet", "/stream", "/image-proxy", "/metadata")
_RATE_LIMIT_WINDOW_S = 60.0
_rate_hits: dict[str, list[float]] = {}
_rate_last_prune = 0.0


class _RateLimitMiddleware:
    """Opt-in sliding-window per-IP rate limiter (pure ASGI so it never buffers
    the streaming response body).

    Off by default — set ``LEAKSHEET_RATE_LIMIT_PER_MIN`` to a positive integer
    to cap requests-per-minute-per-IP on the expensive endpoints. Single-worker
    (see Procfile), so in-process counters are authoritative. The limit is read
    per request so it can be tuned without a redeploy.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self._should_limit(scope):
            resp = Response(
                status_code=429,
                content="Too Many Requests",
                headers={"Retry-After": str(int(_RATE_LIMIT_WINDOW_S))},
            )
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _should_limit(self, scope) -> bool:
        try:
            limit = int(os.environ.get("LEAKSHEET_RATE_LIMIT_PER_MIN", "0") or 0)
        except ValueError:
            limit = 0
        if limit <= 0:
            return False
        path = scope.get("path", "").rstrip("/")
        if not any(path.endswith(p) for p in _RATE_LIMIT_PATHS):
            return False
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        now = time.monotonic()
        cutoff = now - _RATE_LIMIT_WINDOW_S
        hits = _rate_hits.setdefault(ip, [])
        del hits[: _bisect_right(hits, cutoff)]
        self._maybe_prune(now, cutoff)
        if len(hits) >= limit:
            return True
        hits.append(now)
        return False

    @staticmethod
    def _maybe_prune(now: float, cutoff: float) -> None:
        global _rate_last_prune
        if now - _rate_last_prune <= _RATE_LIMIT_WINDOW_S:
            return
        _rate_last_prune = now
        for k in [k for k, v in _rate_hits.items() if not v or v[-1] < cutoff]:
            _rate_hits.pop(k, None)


def _bisect_right(sorted_ts: list[float], value: float) -> int:
    """Index of the first timestamp > value (list is monotonically increasing)."""
    import bisect
    return bisect.bisect_right(sorted_ts, value)


app.add_middleware(_RateLimitMiddleware)

# CORS is added LAST so it is the OUTERMOST middleware: add_middleware makes the
# last-added middleware outermost, and CORS must wrap the rate limiter so a 429
# still carries Access-Control-Allow-Origin (else a browser sees a network error
# instead of a clean 429).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition", "ETag", "X-Cache-Status"],
)


# ---------------------------------------------------------------------------
# POST /api/sheet — parse a tracker URL → full Artist JSON
# ---------------------------------------------------------------------------

# Background revalidation — prevents thundering herd on stale cache
_revalidating: set[str] = set()


async def _background_revalidate(url: str, artist_name: str | None) -> None:
    """Re-fetch and re-parse a tracker URL in the background to refresh cache."""
    url_key = url.strip().lower()
    if url_key in _revalidating:
        return
    _revalidating.add(url_key)
    try:
        await async_fetch_and_parse(
            url, artist_name=artist_name, cache_ttl=0, use_cache=True
        )
        logger.info("Background revalidation complete: %s", url[:80])
    except Exception as e:
        logger.warning("Background revalidation failed for %s: %s", url[:80], e)
    finally:
        _revalidating.discard(url_key)


# Stale-cache prewarm — refresh parses inside the stale-while-revalidate gap
# so trackers people actually use serve fresh data instead of stale-first.
_PREWARM_INTERVAL_S = float(os.environ.get("LEAKSHEET_PREWARM_INTERVAL", "3600"))
_PREWARM_BATCH = int(os.environ.get("LEAKSHEET_PREWARM_BATCH", "25"))


async def _refresh_stale_once(limit: int = _PREWARM_BATCH) -> int:
    """Revalidate up to ``limit`` stale cached parses; returns how many ran.

    Sequential on purpose — this is background politeness work, not a sweep.
    Reuses ``_background_revalidate`` so the per-URL single-flight guard also
    covers request-triggered revalidations of the same tracker.
    """
    urls = await asyncio.to_thread(stale_parsed_cache_urls, limit)
    for url in urls:
        await _background_revalidate(url, None)
    return len(urls)


async def _prewarm_loop() -> None:
    while True:
        await asyncio.sleep(_PREWARM_INTERVAL_S)
        try:
            refreshed = await _refresh_stale_once()
            if refreshed:
                logger.info("Prewarm: revalidated %d stale tracker(s)", refreshed)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — the loop must survive anything
            logger.warning("Prewarm pass failed: %s", e)


def _parse_if_none_match(header_value: str) -> str:
    """Extract the opaque tag from an `If-None-Match` header value.

    Per RFC 7232 §2.3, an ETag may be strong (`"abc"`) or weak (`W/"abc"`),
    and `If-None-Match` may carry one or more comma-separated entries or `*`.
    We only ever emit single, strong-shaped ETags, so we accept either form
    on the request side and compare the unwrapped opaque tag. Returns an
    empty string when no usable tag is present.
    """
    if not header_value:
        return ""
    # Only consider the first entry — we never issue multi-ETag responses.
    first = header_value.split(",", 1)[0].strip()
    if not first or first == "*":
        return ""
    if first[:2] in ("W/", "w/"):
        first = first[2:].lstrip()
    return first.strip().strip('"')


class SheetRequest(BaseModel):
    url: str = Field(..., description="Tracker URL (Google Sheets htmlview or custom domain)")
    artist_name: str | None = Field(None, description="Override inferred artist name")
    use_cache: bool = Field(True, description="Whether to use cached data")
    force_refresh: bool = Field(False, description="Force a fresh fetch, ignoring cache")


@app.post("/sheet")
async def parse_sheet(
    req: SheetRequest,
    request: Request,
    response: Response,
    bg: BackgroundTasks,
):
    """Fetch and parse a tracker spreadsheet.

    Supports ETag-based conditional requests (If-None-Match header) and
    stale-while-revalidate: cached data up to 24h old is served instantly
    while a background refresh is triggered.
    """
    use_cache = req.use_cache and not req.force_refresh

    # --- ETag-based 304 fast path ---
    if use_cache:
        if_none_match = _parse_if_none_match(request.headers.get("if-none-match", ""))
        if if_none_match:
            server_etag = await async_get_cached_etag(req.url)
            if server_etag and server_etag == if_none_match:
                age = await async_get_cached_age(req.url)
                if age is not None and age < STALE_CACHE_TTL:
                    if age > DEFAULT_CACHE_TTL:
                        bg.add_task(_background_revalidate, req.url, req.artist_name)
                    return Response(
                        status_code=304,
                        headers={
                            "ETag": f'"{server_etag}"',
                            "X-Cache-Status": "validated",
                            "Cache-Control": _CC_SHEET,
                        },
                    )

    # --- Stale-while-revalidate fast path ---
    # Serves the raw cached JSON bytes: no pydantic validation, no
    # re-serialization, no content re-hash — those cost ~400ms on a 6.5MB
    # artist and were the bulk of warm-request latency.
    if use_cache:
        timer = PhaseTimer()
        with timer.phase("cache_read"):
            cached = await async_get_cached_parsed_bytes(req.url, max_age=STALE_CACHE_TTL)
        if cached is not None:
            raw, etag, age = cached
            if not etag:
                # Legacy cache entry without a stored hash — compute once.
                with timer.phase("etag"):
                    etag = compute_content_hash(json.loads(raw))
            is_stale = age > DEFAULT_CACHE_TTL

            if is_stale:
                bg.add_task(_background_revalidate, req.url, req.artist_name)

            return Response(
                content=raw,
                media_type="application/json",
                headers={
                    "ETag": f'"{etag}"',
                    "X-Cache-Status": "stale" if is_stale else "hit",
                    "Cache-Control": _CC_SHEET,
                    "Server-Timing": timer.server_timing_header(),
                },
            )

    # --- Cache miss: full fetch + parse ---
    timer = PhaseTimer()
    try:
        artist = await async_fetch_and_parse(
            req.url,
            artist_name=req.artist_name,
            cache_ttl=0 if req.force_refresh else DEFAULT_CACHE_TTL,
            use_cache=use_cache,
            # A force-refresh skips cache reads but must still repopulate it,
            # otherwise the next normal request pays another full cold fetch.
            write_cache=req.use_cache,
            timer=timer,
        )
    except InvalidURLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid URL: {e}")
    except AccessDeniedError as e:
        raise HTTPException(status_code=403, detail=f"Access denied: {e}")
    except NetworkError as e:
        raise HTTPException(status_code=502, detail=f"Network error: {e}")
    except NoTablesError as e:
        raise HTTPException(status_code=404, detail=f"No table data found: {e}")
    except ParseError as e:
        raise HTTPException(status_code=422, detail=f"Parse error: {e}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse: {e}")
    except Exception as e:
        logger.exception("Unhandled error during sheet parse: %s", e)
        raise HTTPException(status_code=500, detail="Internal error")

    # Serialize + hash cost ~600ms on a Ye-sized artist — run off the event
    # loop so concurrent requests aren't stalled during a cold miss.
    def _serialize_and_hash() -> tuple[dict, str]:
        d = artist.model_dump()
        return d, compute_content_hash(d)

    with timer.phase("serialize"):
        data, etag = await asyncio.to_thread(_serialize_and_hash)
    response.headers["ETag"] = f'"{etag}"'
    response.headers["X-Cache-Status"] = "miss"
    response.headers["Cache-Control"] = _CC_SHEET
    response.headers["Server-Timing"] = timer.server_timing_header()
    logger.info("sheet_timing url=%s status=miss %s", req.url[:80], timer.log_line())
    return data


# ---------------------------------------------------------------------------
# POST /cache/clear — clear the fetch cache (served as /api/cache/clear in prod)
# ---------------------------------------------------------------------------

@app.post("/cache/clear")
async def clear_fetch_cache(request: Request):
    """Clear the URL fetch cache (privileged).

    CORS is open (`allow_origins=["*"]`) and this mutates shared server state,
    so an unauthenticated endpoint would let any web page flush the cache and
    force cold refetches for everyone. Requires the admin token: set
    ``LEAKSHEET_ADMIN_TOKEN`` and send it as the ``X-Admin-Token`` header. When
    the token is unset the endpoint is disabled (fail closed — behind a reverse
    proxy the client IP is the proxy, so loopback checks aren't trustworthy).
    """
    admin_token = os.environ.get("LEAKSHEET_ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(
            status_code=503,
            detail="cache clear disabled: set LEAKSHEET_ADMIN_TOKEN to enable",
        )
    provided = request.headers.get("x-admin-token", "")
    # Compare bytes: hmac.compare_digest raises TypeError on non-ASCII str.
    if not hmac.compare_digest(provided.encode("utf-8"), admin_token.encode("utf-8")):
        raise HTTPException(status_code=401, detail="invalid or missing admin token")
    # Off the event loop: the sweep unlinks thousands of files on a busy box.
    cleared, skipped = await asyncio.to_thread(clear_cache)
    return {"cleared": cleared, "skipped": skipped}


# ---------------------------------------------------------------------------
# GET /api/image-proxy — proxy images with CORS headers, optional resizing
# ---------------------------------------------------------------------------

# Width buckets bound the cache cardinality; clients snap to the next bucket.
# 1600 added 2026-07-17: the old 1280 top bucket sat below iPhone full-screen
# width (~1290px), so Now Playing art was upscaled on device.
_IMAGE_SIZE_BUCKETS = (128, 320, 640, 1280, 1600)
_IMAGE_CACHE_TTL = 7 * 86400          # resized results are valid for a week
_IMAGE_CACHE_MAX_BYTES = 200 * 1024 * 1024
_IMAGE_RESIZE_INPUT_CAP = 15 * 1024 * 1024  # don't decode >15MB on the 512MB box
# Compressed-byte size says nothing about decoded size (a small, highly
# compressible image can unpack to hundreds of MB) — cap decoded pixels too,
# checked from the header before the full-frame load() below.
_IMAGE_MAX_DECODE_PIXELS = 20_000_000  # ~80MB peak as RGBA on the 512MB box

# Only lh3-lh6 accept arbitrary =sNNN sizing; lh7-rt 403s and
# docs.google.com/sheets-images 302s to login for N>0 (see web
# enhanceGoogleImageUrl) — those fall through to the Pillow path.
_GOOGLE_RESIZABLE_HOST_RE = re.compile(r"^lh[3-6]\.googleusercontent\.com$", re.IGNORECASE)
# Google's sizing suffix is a "="-prefixed, "-"-joined list of option tokens,
# not just w/h/s: "no" (don't upscale), "c" (crop), "p" (padding), etc. all
# appear with no following digits, so a token is letters + *optional* digits
# rather than one of {s,w,h} + required digits.
_GOOGLE_SIZE_SUFFIX_RE = re.compile(r"=[a-zA-Z]+\d*(-[a-zA-Z]+\d*)*$")


def _snap_image_width(w: int) -> int:
    for bucket in _IMAGE_SIZE_BUCKETS:
        if w <= bucket:
            return bucket
    return _IMAGE_SIZE_BUCKETS[-1]


def _rewrite_google_size(url: str, w: int) -> str | None:
    """Rewrite an lh3-lh6 googleusercontent URL to request width ``w`` from
    Google's CDN directly (free resize, no local decode). Returns None when
    the host doesn't support arbitrary sizing. Never changes host or path,
    so the SSRF allowlist verdict on the original URL still holds.
    """
    from urllib.parse import urlparse
    hostname = urlparse(url).hostname or ""
    if not _GOOGLE_RESIZABLE_HOST_RE.match(hostname):
        return None
    return _GOOGLE_SIZE_SUFFIX_RE.sub("", url) + f"=s{w}"


def _image_cache_key(url: str, w: int | None) -> str:
    return hashlib.sha256(f"{url}|{w or 0}".encode()).hexdigest()


def _image_cache_paths(key: str):
    return CACHE_DIR / f"img_{key}.bin", CACHE_DIR / f"img_{key}.meta.json"


def _read_image_cache(key: str) -> tuple[bytes, str] | None:
    """Blocking read of a cached resized image — call via asyncio.to_thread."""
    bin_path, meta_path = _image_cache_paths(key)
    try:
        meta = json.loads(meta_path.read_text())
        if time.time() - meta["timestamp"] > _IMAGE_CACHE_TTL:
            return None
        return bin_path.read_bytes(), meta["content_type"]
    except (OSError, ValueError, KeyError):
        return None


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a same-directory temp file + rename, so a concurrent
    reader never observes a truncated/partial file mid-write."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _write_image_cache(key: str, data: bytes, content_type: str) -> None:
    """Blocking write + size-cap eviction — call via asyncio.to_thread."""
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        bin_path, meta_path = _image_cache_paths(key)
        meta_bytes = json.dumps({
            "content_type": content_type,
            "timestamp": time.time(),
        }).encode()
        _atomic_write_bytes(bin_path, data)
        _atomic_write_bytes(meta_path, meta_bytes)
        _evict_image_cache()
    except OSError as e:
        logger.warning("Image cache write failed: %s", e)


def _evict_image_cache() -> None:
    """Drop oldest resized images (by mtime) once the cache exceeds the cap."""
    entries = []
    total = 0
    for bin_path in CACHE_DIR.glob("img_*.bin"):
        try:
            stat = bin_path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, bin_path))
        total += stat.st_size
    entries.sort()
    while entries and total > _IMAGE_CACHE_MAX_BYTES:
        _, size, victim = entries.pop(0)
        total -= size
        meta = victim.with_name(victim.name[:-4] + ".meta.json")
        for p in (victim, meta):
            try:
                p.unlink()
            except OSError:
                pass


def _resize_image_bytes(data: bytes, w: int, content_type: str) -> tuple[bytes, str]:
    """Blocking Pillow downscale to max width ``w`` — call via asyncio.to_thread.

    Returns the original bytes when the image is already small enough, too
    large to decode safely, or not decodable.
    """
    if len(data) > _IMAGE_RESIZE_INPUT_CAP:
        return data, content_type
    import io

    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > _IMAGE_MAX_DECODE_PIXELS:
            return data, content_type
        img.load()
    except Exception as exc:
        # Serve the original bytes, but leave a trace — a systematically
        # undecodable source would otherwise be invisible.
        logger.warning("image resize: decode failed (%s) — serving original", exc)
        return data, content_type
    if img.width <= w:
        return data, content_type

    img.thumbnail((w, 10 * w))
    has_alpha = "A" in img.getbands() or (
        img.mode == "P" and "transparency" in img.info
    )
    buf = io.BytesIO()
    if has_alpha:
        img.convert("RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue(), "image/jpeg"


@app.get("/image-proxy")
async def proxy_image(
    request: Request,
    url: str = Query(..., description="Image URL to proxy"),
    w: int | None = Query(None, ge=32, le=1600, description="Max width in pixels"),
):
    """Proxy an image through the backend to avoid CORS issues.

    With ``w`` the image is downscaled — via Google's CDN when the host
    supports ``=sNNN`` sizing, else locally with Pillow (result disk-cached
    in CACHE_DIR as flat ``img_*`` files, cleared by /cache/clear).
    """
    # Fix protocol-relative URLs
    if url.startswith("//"):
        url = "https:" + url

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")

    if not _is_allowed_domain(url, _IMAGE_ALLOWED_DOMAINS, _IMAGE_ALLOWED_PARENT_DOMAINS):
        raise HTTPException(status_code=403, detail="Domain not allowed for image proxy")

    width = _snap_image_width(w) if w else None
    base_headers = {
        "Cache-Control": _CC_IMAGE,
        "Access-Control-Allow-Origin": "*",
    }

    # Only width-bounded requests are disk-cached, so only they can carry an
    # ETag — one that reflects a real, still-live cache entry rather than a
    # pure hash of the request, otherwise an expired or /cache/clear'd entry
    # (or an unsized request, which is never cached at all) would revalidate
    # as unchanged forever.
    cache_key = None
    cached = None
    if width is not None:
        cache_key = _image_cache_key(url, width)
        cached = await asyncio.to_thread(_read_image_cache, cache_key)
        if cached is not None:
            base_headers["ETag"] = f'"{cache_key}"'
            if _parse_if_none_match(request.headers.get("if-none-match", "")) == cache_key:
                return Response(status_code=304, headers=base_headers)

    # Conditional headers — send browser-like headers for Google domains
    is_google = any(h in url for h in (
        'googleusercontent.com', 'ggpht.com', 'google.com', 'gstatic.com',
    ))
    headers = {}
    if is_google:
        headers["Referer"] = "https://docs.google.com/"

    try:
        if width is not None:
            if cached is not None:
                data, ct = cached
                return Response(
                    content=data, media_type=ct,
                    headers={**base_headers, "X-Cache-Status": "hit"},
                )

            # Prefer Google-side resizing — no local decode, no disk cache
            # needed (the CDN did the work).
            google_url = _rewrite_google_size(url, width)
            if google_url is not None:
                try:
                    resp = await _get_proxy_client().get(google_url, headers=headers)
                    ct = resp.headers.get("content-type", "")
                    if resp.status_code == 200 and ct.startswith("image/"):
                        return Response(
                            content=resp.content, media_type=ct,
                            headers={**base_headers, "X-Cache-Status": "origin"},
                        )
                except httpx.HTTPError as exc:
                    # Fall through to the original URL + Pillow path.
                    logger.warning("image proxy: Google CDN resize failed for %s: %s", url[:80], exc)

        resp = await _get_proxy_client().get(url, headers=headers)
        ct = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ct.startswith("image/"):
            data = resp.content
            if width is not None:
                data, ct = await asyncio.to_thread(_resize_image_bytes, data, width, ct)
                await asyncio.to_thread(_write_image_cache, cache_key, data, ct)
                base_headers["ETag"] = f'"{cache_key}"'
                status = "miss"
            else:
                status = "origin"
            return Response(
                content=data, media_type=ct,
                headers={**base_headers, "X-Cache-Status": status},
            )

        raise HTTPException(
            status_code=resp.status_code,
            detail="Upstream image fetch failed",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Image proxy error: %s", e)
        raise HTTPException(status_code=502, detail="Image proxy error")


# ---------------------------------------------------------------------------
# GET /api/metadata — fetch audio file metadata from provider APIs
# ---------------------------------------------------------------------------

_METADATA_USER_AGENT = USER_AGENT  # shared backend UA from src.config


class _TTLCache:
    """In-memory TTL cache with a size cap (oldest-inserted eviction)."""

    def __init__(self, ttl: float, max_entries: int) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._data: dict[str, tuple[float, object]] = {}

    def get(self, key: str) -> object | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: object) -> None:
        if key not in self._data and len(self._data) >= self.max_entries:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest, None)
        self._data[key] = (time.monotonic(), value)


# Provider metadata rarely changes for a given file — cache parsed results so
# repeated description-sheet opens don't re-hit provider APIs.
_metadata_cache = _TTLCache(ttl=3600.0, max_entries=500)


# Known fields in pillows.su metadata — longer multi-word keys first to avoid
# partial matches (e.g. "CODEC PROFILE" before "CODEC").
_PILLOWS_FIELDS = [
    "FILE FORMAT INFO", "COMMON INFO",
    "CODEC PROFILE", "CODEC", "CONTAINER",
    "DURATION", "BITRATE", "SAMPLE RATE", "BITS PER SAMPLE",
    "LOSSLESS", "NUMBER OF CHANNELS",
    "CREATION TIME", "MODIFICATION TIME",
    "TRACK GAIN", "ALBUM GAIN",
    "ALBUM ARTIST", "ARTIST", "ALBUM", "TITLE", "TRACK",
    "GENRE", "DATE", "YEAR", "COMMENT",
]
_PILLOWS_SPLIT_RE = re.compile(
    r"(" + "|".join(re.escape(f) for f in _PILLOWS_FIELDS) + r"):\s*"
)


# Codec is the strongest audio/video signal — mp4/mov containers hold
# audio-only m4a files too, so an ambiguous container without codec info
# stays "unknown". Substring-tolerant: pillows strings look like
# "H.264 High Profile" or "AAC LC".
_VIDEO_CODEC_RE = re.compile(
    r"h\.?264|avc|hevc|h\.?265|av1|vp[89]|mpeg-?4 video|xvid|divx", re.IGNORECASE
)
_AUDIO_CODEC_RE = re.compile(
    r"aac|mp3|mpeg[- ]?\d? layer|flac|alac|opus|vorbis|pcm|wav|ac-?3|dts", re.IGNORECASE
)
_AUDIO_CONTAINER_RE = re.compile(
    r"flac|mp3|mpeg audio|wav|wave|ogg|aiff", re.IGNORECASE
)


def _media_kind_from_mime(mime: str | None) -> str:
    """Classify from a Content-Type/mime string ("video/mp4" → "video")."""
    m = (mime or "").lower()
    if m.startswith("video/"):
        return "video"
    if m.startswith("audio/"):
        return "audio"
    return "unknown"


def _derive_media_kind(container: str | None, codec: str | None) -> str:
    """Classify a file as "audio" | "video" | "unknown" from metadata strings.

    This is the only video signal clients get for opaque stream-host URLs —
    the pillows stream endpoint reports audio/mp4 regardless of content.
    """
    if codec:
        if _VIDEO_CODEC_RE.search(codec):
            return "video"
        if _AUDIO_CODEC_RE.search(codec):
            return "audio"
    if container and _AUDIO_CONTAINER_RE.search(container):
        return "audio"
    return "unknown"


def _parse_pillows_metadata(text: str) -> dict:
    """Parse pillows.su metadata text format into normalized dict.

    The response can be either newline-separated or a single continuous
    string with no delimiters — use regex to split on known field names.
    """
    result: dict = {"provider": "pillows"}
    parts = _PILLOWS_SPLIT_RE.split(text.strip())
    # parts is [preamble, KEY1, VAL1, KEY2, VAL2, ...]
    pairs: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        key = parts[i].strip().upper()
        val = parts[i + 1].strip()
        if val and val.lower() not in ("unknown", "null", "[object object]"):
            pairs[key] = val

    if "CONTAINER" in pairs:
        result["container"] = pairs["CONTAINER"]
    if "CODEC" in pairs:
        result["codec"] = pairs["CODEC"]
    if "CODEC PROFILE" in pairs:
        result["codec_profile"] = pairs["CODEC PROFILE"]
    if "BITRATE" in pairs:
        result["bitrate"] = pairs["BITRATE"]
    if "SAMPLE RATE" in pairs:
        result["sample_rate"] = pairs["SAMPLE RATE"]
    if "BITS PER SAMPLE" in pairs:
        result["bits_per_sample"] = pairs["BITS PER SAMPLE"]
    if "LOSSLESS" in pairs:
        result["lossless"] = pairs["LOSSLESS"].lower() == "true"
    if "NUMBER OF CHANNELS" in pairs:
        v = pairs["NUMBER OF CHANNELS"]
        result["channels"] = int(v) if v.isdigit() else v
    if "DURATION" in pairs:
        result["duration"] = pairs["DURATION"]
    if "ARTIST" in pairs:
        result["artist"] = pairs["ARTIST"]
    if "TITLE" in pairs:
        result["title"] = pairs["TITLE"]
    result["media_kind"] = _derive_media_kind(result.get("container"), result.get("codec"))
    return result


def _parse_froste_metadata(data: dict) -> dict:
    """Normalize froste.lol analyze-quality JSON."""
    result: dict = {"provider": "froste"}
    if "estimatedBitrate" in data:
        result["estimated_bitrate"] = round(data["estimatedBitrate"])
        result["bitrate"] = f"{round(data['estimatedBitrate'])}kbps"
    if "frequencyCutoff" in data:
        result["frequency_cutoff"] = round(data["frequencyCutoff"], 1)
    if "qualityMismatch" in data:
        result["quality_mismatch"] = data["qualityMismatch"]
    return result


def _parse_imgur_metadata(data: dict) -> dict:
    """Extract useful fields from imgur.gg file API response."""
    result: dict = {"provider": "imgur"}
    if data.get("size"):
        result["file_size"] = data["size"]
    if data.get("mimeType"):
        result["mime_type"] = data["mimeType"]
    if data.get("name"):
        result["filename"] = data["name"]
    result["media_kind"] = _media_kind_from_mime(data.get("mimeType"))
    return result


def _parse_pixeldrain_metadata(data: dict) -> dict:
    """Extract useful fields from pixeldrain.com's /api/file/{id}/info response."""
    result: dict = {"provider": "pixeldrain"}
    if data.get("name"):
        result["filename"] = data["name"]
    if data.get("size") is not None:
        result["file_size"] = data["size"]
    if data.get("mime_type"):
        result["mime_type"] = data["mime_type"]
    result["media_kind"] = _media_kind_from_mime(data.get("mime_type"))
    return result


async def _pillows_stream_head_fallback(file_url: str) -> dict | None:
    """Minimal metadata from a HEAD of the pillows stream URL (mime + size).

    Used when the .txt metadata endpoint has no entry for a file. Returns
    None on any failure so the caller falls through to its normal error.
    """
    stream_url = resolve_stream_url(file_url)
    if not stream_url:
        return None
    try:
        client = _get_shared_client()
        resp = await client.head(
            stream_url,
            headers={"User-Agent": _METADATA_USER_AGENT, "Referer": "https://pillows.su/"},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        mime = resp.headers.get("content-type")
        result: dict = {
            "provider": "pillows",
            "media_kind": _media_kind_from_mime(mime),
        }
        if mime:
            result["mime_type"] = mime.split(";")[0].strip()
        size = resp.headers.get("content-length")
        if size and size.isdigit():
            result["file_size"] = int(size)
        return result
    except Exception as exc:
        # None → caller 404s; log so a persistent provider outage is
        # distinguishable from a genuinely missing file.
        logger.warning("pillows HEAD fallback failed for %s: %s", file_url[:80], exc)
        return None


@app.get("/metadata")
async def proxy_metadata(
    url: str = Query(..., description="Original file-sharing link"),
):
    """Fetch audio file metadata from provider APIs."""
    meta_info = resolve_metadata_url(url)
    if not meta_info:
        raise HTTPException(status_code=404, detail="No metadata API for this provider")

    meta_url = meta_info["url"]
    provider = meta_info["provider"]

    cached = _metadata_cache.get(meta_url)
    if cached is not None:
        return Response(
            content=cached,
            media_type="application/json",
            headers={
                "Cache-Control": _CC_METADATA,
                "X-Cache-Status": "hit",
            },
        )

    headers: dict[str, str] = {"User-Agent": _METADATA_USER_AGENT}
    if provider == "pillows":
        headers["Referer"] = "https://pillows.su/"
    elif provider == "froste":
        headers["Referer"] = meta_url.rsplit("/analyze-quality", 1)[0]

    try:
        client = _get_shared_client()
        resp = await client.get(meta_url, headers=headers)
        if resp.status_code != 200:
            # pillows' metadata .txt endpoint 404s for some files — notably
            # videos. The CDN's Content-Type on the stream URL is accurate,
            # so fall back to a HEAD probe before giving up.
            if provider == "pillows":
                fallback = await _pillows_stream_head_fallback(url)
                if fallback is not None:
                    payload = json.dumps(fallback)
                    _metadata_cache.set(meta_url, payload)
                    return Response(
                        content=payload,
                        media_type="application/json",
                        headers={
                            "Cache-Control": _CC_METADATA,
                            "X-Cache-Status": "miss",
                        },
                    )
            raise HTTPException(
                status_code=502,
                detail=f"Provider returned {resp.status_code}",
            )

        if provider == "pillows":
            result = _parse_pillows_metadata(resp.text)
        elif provider == "froste":
            result = _parse_froste_metadata(resp.json())
        elif provider == "imgur":
            result = _parse_imgur_metadata(resp.json())
        elif provider == "pixeldrain":
            result = _parse_pixeldrain_metadata(resp.json())
        else:
            result = {"provider": provider}

        payload = json.dumps(result)
        _metadata_cache.set(meta_url, payload)
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Cache-Control": _CC_METADATA,
                "X-Cache-Status": "miss",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Metadata proxy error: %s", e)
        raise HTTPException(status_code=502, detail="Metadata fetch failed")


# ---------------------------------------------------------------------------
# GET /api/trackers — artist tracker discovery from the TrackerHub sheet
# ---------------------------------------------------------------------------


class TrackerEntry(BaseModel):
    """One row of the TrackerHub master sheet — a discoverable artist tracker."""

    name: str
    url: str
    credit: str | None = None
    best: bool = False
    up_to_date: bool | None = None
    working_links: bool | None = None


def _unwrap_google_redirect(url: str) -> str:
    """Resolve a google.com/url?q=… redirect to its target URL."""
    from urllib.parse import parse_qs, urlparse
    try:
        parsed = urlparse(url)
        if parsed.hostname in ("www.google.com", "google.com") and parsed.path == "/url":
            target = parse_qs(parsed.query).get("q")
            if target:
                return target[0]
    except (ValueError, TypeError):
        pass
    return url


def _parse_yes_no(text: str) -> bool | None:
    t = text.strip().lower()
    if t.startswith("yes"):
        return True
    if t.startswith("no"):
        return False
    return None


_TRACKER_STAR_CHARS = "⭐️ "  # ⭐ + variation selector + space


def _parse_trackerhub(html: str) -> list[TrackerEntry]:
    """Parse the TrackerHub sheet into tracker entries.

    Rows: [Trackers (name + link, ⭐ prefix = featured), Credits,
    Up To Date?, Working Links?]. Banner/header rows carry no credit and
    no Yes/No flags, which is what filters them out.
    """
    from src.parser import extract_table

    entries: list[TrackerEntry] = []
    for row in extract_table(html):
        if not row:
            continue
        name_cell = row[0]
        raw_name = name_cell.text.strip()
        if not raw_name or not name_cell.links:
            continue
        credit = row[1].text.strip() if len(row) > 1 else ""
        up_to_date = _parse_yes_no(row[2].text) if len(row) > 2 else None
        working_links = _parse_yes_no(row[3].text) if len(row) > 3 else None
        # Banner rows (rules text, discord invites) have a name/link but
        # neither credits nor status flags — real tracker rows always have
        # at least one of them.
        if not credit and up_to_date is None and working_links is None:
            continue
        best = raw_name.startswith("⭐")
        name = raw_name.lstrip(_TRACKER_STAR_CHARS).strip()
        if not name:
            continue
        entries.append(TrackerEntry(
            name=name,
            url=_unwrap_google_redirect(name_cell.links[0]),
            credit=credit or None,
            best=best,
            up_to_date=up_to_date,
            working_links=working_links,
        ))
    entries.sort(key=lambda e: (not e.best, e.name.lower()))
    return entries


_trackers_cache = _TTLCache(ttl=3600.0, max_entries=1)
# Last successful payload, kept indefinitely as a fallback for upstream errors.
_trackers_stale: str | None = None


@app.get("/trackers")
async def list_trackers():
    """List artist trackers from the TrackerHub master sheet (cached 1h)."""
    global _trackers_stale

    cached = _trackers_cache.get("trackers")
    if cached is not None:
        return Response(
            content=cached,
            media_type="application/json",
            headers={
                "Cache-Control": _CC_METADATA,
                "X-Cache-Status": "hit",
            },
        )

    from src.config import TRACKERHUB_URL
    try:
        resp = await _get_proxy_client().get(
            TRACKERHUB_URL, headers={"Accept": "text/html"}
        )
        if resp.status_code != 200:
            raise NetworkError(f"TrackerHub returned {resp.status_code}")
        entries = await asyncio.to_thread(_parse_trackerhub, resp.text)
        if not entries:
            raise ParseError("No tracker rows parsed from TrackerHub")
        payload = json.dumps([e.model_dump() for e in entries])
        _trackers_cache.set("trackers", payload)
        _trackers_stale = payload
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Cache-Control": _CC_METADATA,
                "X-Cache-Status": "miss",
            },
        )
    except Exception as e:
        logger.exception("TrackerHub fetch failed: %s", e)
        if _trackers_stale is not None:
            return Response(
                content=_trackers_stale,
                media_type="application/json",
                headers={
                    "Cache-Control": _CC_TRACKERS_STALE,
                    "X-Cache-Status": "stale",
                },
            )
        raise HTTPException(status_code=502, detail="TrackerHub fetch failed")


# ---------------------------------------------------------------------------
# GET /api/stream — proxy audio (CORS bypass) with range request support
# ---------------------------------------------------------------------------

class _RangePlan:
    """Decision for serving a client Range when upstream ignored it.

    kind:
      'full'          — serve the whole body as HTTP 200 (no/ignored Range)
      'partial'       — synthesise HTTP 206 for bytes [start, end]
      'unsatisfiable' — HTTP 416 with Content-Range: bytes */total
    """

    __slots__ = ("kind", "start", "end")

    def __init__(self, kind: str, start: int = 0, end: int | None = None):
        self.kind = kind
        self.start = start
        self.end = end

    def __eq__(self, other):
        return (self.kind, self.start, self.end) == (other.kind, other.start, other.end)

    def __repr__(self):
        return f"_RangePlan({self.kind!r}, {self.start}, {self.end})"


_RANGE_SPEC = re.compile(r"^bytes=(?:(\d+)-(\d*)|-(\d+))$")


def _plan_synthesized_range(range_header: str | None, total_size: int | None) -> _RangePlan:
    """Map a client Range header onto a serving plan (RFC 7233 semantics).

    Only single-part byte ranges are synthesised. Malformed or multi-part
    headers are ignored (serve 200 full) rather than rejected — per RFC 7233
    a server MAY ignore the Range header. Suffix ranges ('bytes=-N', which
    AVPlayer uses to read trailing MP4 metadata) resolve against the total
    size when known.
    """
    if not range_header:
        return _RangePlan("full")
    m = _RANGE_SPEC.match(range_header.strip())
    if not m:
        return _RangePlan("full")

    first, last, suffix = m.groups()
    if suffix is not None:
        n = int(suffix)
        if n == 0:
            return _RangePlan("unsatisfiable")  # 'bytes=-0' names no bytes
        if total_size is None:
            # Suffix against an unknown total → can't synthesise a valid
            # Content-Range; fall back to the full body.
            return _RangePlan("full")
        start = max(0, total_size - n)
        return _RangePlan("partial", start, total_size - 1)

    start = int(first)
    if total_size is not None and start >= total_size:
        return _RangePlan("unsatisfiable")
    if not last:
        # Open-ended 'bytes=start-'
        if total_size is None:
            # Unknown total: a synthesised 206 needs a Content-Range end.
            # Serve 200 from byte 0 — signals "Range unsupported" without
            # corrupting Safari's byte→timestamp mapping.
            return _RangePlan("full")
        return _RangePlan("partial", start, total_size - 1)

    end = int(last)
    if end < start:
        return _RangePlan("full")  # malformed → ignore the header
    if total_size is not None:
        end = min(end, total_size - 1)
    return _RangePlan("partial", start, end)


async def _slice_byte_stream(source, range_start: int, range_end: int):
    """Yield only bytes [range_start, range_end] (inclusive) from a chunked stream.

    Used to synthesise HTTP 206 responses when the upstream host ignores
    Range requests. Stops consuming the source once the range is served.
    """
    skipped = 0
    async for chunk in source:
        chunk_end = skipped + len(chunk)
        # Entirely before range_start — skip
        if chunk_end <= range_start:
            skipped += len(chunk)
            continue
        # Compute the slice of this chunk we need
        start_in_chunk = max(0, range_start - skipped)
        end_in_chunk = min(len(chunk), range_end + 1 - skipped)
        portion = chunk[start_in_chunk:end_in_chunk]
        if portion:
            yield portion
        skipped += len(chunk)
        # Past range_end — stop
        if skipped > range_end:
            break


@app.get("/stream")
async def proxy_stream(
    request: Request,
    url: str = Query(..., description="Original file-sharing link"),
    download: bool = Query(False, description="Set Content-Disposition for download"),
):
    """Proxy an audio stream from a supported file-sharing host.

    Supports HTTP Range requests for proper seeking.
    When upstream doesn't support Range, synthesises partial responses locally.
    Pass ?download=true to get a Content-Disposition: attachment header.
    """
    stream_url = resolve_stream_url(url)
    if stream_url is None:
        raise HTTPException(status_code=400, detail="URL is not from a supported streaming host")

    if not _is_allowed_domain(stream_url, _STREAM_ALLOWED_DOMAINS):
        raise HTTPException(status_code=403, detail="Domain not allowed for audio streaming")

    # Forward Range header from client if present. Malformed or multi-part
    # headers are ignored per RFC 7233 (serve 200 full) rather than being
    # forwarded — upstreams turn garbage Range values into hard errors.
    range_header = request.headers.get("range")
    if range_header and not _RANGE_SPEC.match(range_header.strip()):
        range_header = None

    # Parse range shape early — needed for the MIME sniffing decision below.
    _range_start = 0
    _is_suffix_range = False
    if range_header:
        _rs_m = re.match(r"bytes=(\d+)-", range_header)
        if _rs_m:
            _range_start = int(_rs_m.group(1))
        else:
            _is_suffix_range = bool(re.match(r"bytes=-\d+", range_header))

    try:
        resp = await stream_audio(stream_url, range_header=range_header)
    except GdriveInterstitialError as e:
        # Google Drive returned (and kept returning, after the confirm
        # retry) an HTML virus-scan interstitial instead of file bytes.
        # Never proxy HTML as audio — tell the client to fall back to
        # opening the original share link in a browser.
        logger.warning("gdrive interstitial for %s: %s", stream_url, e)
        raise HTTPException(status_code=409, detail="gdrive_interstitial")
    except ValueError as e:
        logger.warning("Stream error for %s: %s", stream_url, e)
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("Stream error for %s: %s", stream_url, e)
        raise HTTPException(status_code=502, detail="Upstream error")

    # Permission-required/private gdrive files come back from stream_audio
    # as a real 403 response object (not raised) — relay it as-is.
    if resp.status_code == 403:
        await resp.aclose()
        raise HTTPException(status_code=403, detail="Provider denied access")

    # Upstream judged the (valid) range unsatisfiable — relay it faithfully
    # instead of collapsing it into a generic 502.
    if resp.status_code == 416:
        cr = resp.headers.get("content-range")
        await resp.aclose()
        return Response(
            status_code=416,
            headers={"Content-Range": cr} if cr else {"Content-Range": "bytes */*"},
        )

    raw_ct = resp.headers.get("content-type")
    raw_cd = resp.headers.get("content-disposition")
    ct = _fix_audio_mime(raw_ct, url=str(resp.url), content_disposition=raw_cd)
    total_size = int(resp.headers["content-length"]) if "content-length" in resp.headers else None

    # ---------------------------------------------------------------------------
    # MIME sniffing — some hosts (e.g. pillows.su) always report "audio/mp4"
    # regardless of actual container format.  Chrome lenient-decodes the bytes;
    # Safari strictly validates Content-Type against actual data → "Source not
    # supported" when an Ogg file is served as audio/mp4.
    #
    # When the range starts at byte 0 we can see the file header, so we read
    # the first chunk, detect the real format from magic bytes, and correct ct.
    # The chunk is prepended back into the stream so no bytes are lost.
    # ---------------------------------------------------------------------------
    _stream_iter = resp.aiter_bytes(chunk_size=65536)
    _prepend_chunk: bytes = b""

    # The first body byte is file byte 0 when upstream ignored the Range
    # (200), or honored a range that starts at 0. A 206 to a suffix range
    # ('bytes=-N') starts at the file TAIL — never sniff those bytes.
    _body_starts_at_zero = resp.status_code == 200 or (
        _range_start == 0 and not _is_suffix_range
    )
    if _body_starts_at_zero:
        try:
            _prepend_chunk = await _stream_iter.__anext__()
        except StopAsyncIteration:
            _prepend_chunk = b""
        except Exception as exc:
            # A read error (upstream stall/reset) while sniffing the first chunk
            # would otherwise escape without closing `resp`, leaking its pooled
            # connection until it times out. Close it and surface a 502.
            await resp.aclose()
            logger.warning("stream first-chunk read failed for %s: %s", url[:80], exc)
            raise HTTPException(status_code=502, detail="Upstream read error") from exc
        sniffed = _sniff_audio_format(_prepend_chunk[:16] if _prepend_chunk else b"")
        if sniffed:
            ct = sniffed

    # When ?download=true, add Content-Disposition with correct extension
    if download:
        ext = _MIME_TO_EXT.get(ct, ".mp3")
        _disposition = f'attachment; filename="track{ext}"'
    else:
        _disposition = None

    async def _iter_upstream():
        """Prepend the sniffed first chunk, then relay the upstream body."""
        if _prepend_chunk:
            yield _prepend_chunk
        async for chunk in _stream_iter:
            yield chunk

    async def _closing(iterator):
        """Relay *iterator*, guaranteeing the upstream response is closed.

        Every response path below wraps its byte source in this — previously
        each branch had its own near-identical generator.
        """
        try:
            async for chunk in iterator:
                yield chunk
        finally:
            await resp.aclose()

    # ---------- upstream DID handle Range → pass through as-is ----------
    if resp.status_code == 206:
        headers: dict[str, str] = {"Accept-Ranges": "bytes"}
        if _disposition:
            headers["Content-Disposition"] = _disposition
        if ct:
            headers["Content-Type"] = ct
        cr = resp.headers.get("content-range")
        if cr:
            headers["Content-Range"] = cr
            # Derive Content-Length from Content-Range — some upstreams
            # (e.g. pillows.su) return the *total* file size in
            # Content-Length even for 206 responses, which breaks iOS Safari.
            cr_match = re.match(r"bytes (\d+)-(\d+)/", cr)
            if cr_match:
                headers["Content-Length"] = str(
                    int(cr_match.group(2)) - int(cr_match.group(1)) + 1
                )
        if "Content-Length" not in headers:
            cl = resp.headers.get("content-length")
            if cl:
                headers["Content-Length"] = cl

        return StreamingResponse(
            _closing(_iter_upstream()),
            status_code=206,
            headers=headers,
            media_type=ct or "application/octet-stream",
        )

    # ---------- upstream returned 200 (no Range support) ----------------
    # If the client didn't ask for Range either, just pass the full body.
    if not range_header:
        headers = {"Accept-Ranges": "bytes"}
        if _disposition:
            headers["Content-Disposition"] = _disposition
        if ct:
            headers["Content-Type"] = ct
        if total_size is not None:
            headers["Content-Length"] = str(total_size)

        return StreamingResponse(
            _closing(_iter_upstream()),
            status_code=200,
            headers=headers,
            media_type=ct or "application/octet-stream",
        )

    # Client requested Range but upstream ignored it — plan the response.
    # (Suffix ranges resolve against total size; malformed headers are
    # ignored per RFC 7233; unsatisfiable starts get a proper 416.)
    plan = _plan_synthesized_range(range_header, total_size)

    if plan.kind == "unsatisfiable":
        await resp.aclose()
        cr_total = str(total_size) if total_size is not None else "*"
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{cr_total}"},
        )

    if plan.kind == "full":
        # Cannot synthesise a valid 206 (unknown total, or header ignored).
        # Return the full stream from byte 0 as HTTP 200, which correctly
        # signals that Range is not supported for this response. iOS Safari
        # interprets HTTP 200 to a Range request as "full file from byte 0";
        # returning partial data here would corrupt its byte-offset-to-
        # timestamp mapping.
        _unknown_headers: dict[str, str] = {
            "Accept-Ranges": "bytes",
            "Content-Type": ct or "application/octet-stream",
        }
        if _disposition:
            _unknown_headers["Content-Disposition"] = _disposition

        return StreamingResponse(
            _closing(_iter_upstream()),
            status_code=200,
            headers=_unknown_headers,
            media_type=ct or "application/octet-stream",
        )

    # Synthesise a 206 with Content-Range ('*' total is valid per RFC 7233
    # when the complete length is unknown).
    range_start, range_end = plan.start, plan.end
    content_length = range_end - range_start + 1

    # The slice operates on the FULL byte-offset stream (prepend chunk first).
    return StreamingResponse(
        _closing(_slice_byte_stream(_iter_upstream(), range_start, range_end)),
        status_code=206,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Type": ct or "application/octet-stream",
            "Content-Length": str(content_length),
            "Content-Range": (
                f"bytes {range_start}-{range_end}/"
                f"{total_size if total_size is not None else '*'}"
            ),
        },
        media_type=ct or "application/octet-stream",
    )
