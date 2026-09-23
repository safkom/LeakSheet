"""LeakSheet — FastAPI HTTP layer.

Endpoints:
  POST /sheet       — send a tracker URL, get parsed Artist JSON back
                      (ETag / stale-while-revalidate)
  GET  /trackers    — ArtistGrid discovery list, best-first
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
import bisect
import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import StreamingResponse

from src.config import (
    USER_AGENT,
    curated_host_allowed,
)
from src.models import Artist, TrackerEntry, slugify
from src.tracker_seed import SEED_TRACKERS
from src.fetcher import (
    AccessDeniedError,
    CACHE_DIR,
    _atomic_write_bytes,
    _normalize_url,
    async_fetch_and_parse,
    async_get_cached_age,
    async_get_cached_etag,
    async_get_cached_parsed_bytes,
    clear_cache,
    close_sheets_client,
    fetch_artistgrid_entries,
    serialize_artist,
    content_hash,
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
    TTLCache,
    UpstreamStatusError,
    close_shared_client,
    resolve_metadata_url,
    resolve_stream_url,
    stream_audio,
    _get_shared_client,
)

logger = logging.getLogger(__name__)


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

# Audio format sniffing — see docs/decisions.md::api.py::mime-sniffing

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
# (every /sheet response also carries Vary: Accept — it is JSON or NDJSON by Accept)
_CC_IMAGE = "public, max-age=86400"     # /image-proxy — immutable art, 1 day
_CC_METADATA = "public, max-age=3600"   # /metadata + /trackers — hourly TTL caches
_CC_TRACKERS_STALE = "public, max-age=600"  # /trackers stale fallback — retry sooner


# ---------------------------------------------------------------------------
# SSRF protection — domain allowlists for proxy endpoints
# ---------------------------------------------------------------------------

_IMAGE_ALLOWED_DOMAINS = {
    # Misc-tab thumbnails. MiscLinkClassifier.thumbnailURL derives these two
    # for YouTube embeds, and the client routes every thumbnail through this
    # proxy — without them every misc row 403'd and showed a placeholder.
    "img.youtube.com",
    "i.ytimg.com",
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


# Google image CDNs, for the Referer decision below. Parent domains: a
# subdomain of any of these counts.
_GOOGLE_IMAGE_DOMAINS = {
    "googleusercontent.com", "ggpht.com", "google.com", "gstatic.com",
}


def _image_host_allowed(url: str) -> bool:
    """Hosts the image proxy may fetch from.

    Google's image CDNs, plus the curated tracker seed and
    LEAKSHEET_EXTRA_SHEET_HOSTS. Self-hosted trackers serve era covers from
    their own origin as "/assets/<sha>.jpg", so their hosts have to be here.

    Deliberately NOT the ArtistGrid-harvested hosts that /sheet accepts. That
    feed is third-party: anyone who lands a row in it would otherwise add a host
    to an endpoint that returns bytes to any origin. /sheet still auto-accepts
    feed trackers; a feed-only tracker whose covers are self-hosted needs its
    host added to the seed in src/config.py (or the env var) for art to load.
    """
    if _is_allowed_domain(url, _IMAGE_ALLOWED_DOMAINS, _IMAGE_ALLOWED_PARENT_DOMAINS):
        return True
    return curated_host_allowed(urlparse(url).hostname)


def _is_allowed_domain(url: str, allowed: set[str], parent_domains: set[str] | None = None) -> bool:
    """Check if the URL's hostname is in the explicit allow-list.

    Exact match first. If parent_domains is provided, also accepts any hostname
    that is a direct or nested subdomain of one of those parent domains.
    """
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
    # Prewarm loop — keeps hot trackers out of the stale-first window.
    # LEAKSHEET_PREWARM=0 disables. It sleeps BEFORE its first pass, so
    # startup and TestClient contexts never fire network work.
    # Why: docs/decisions.md.
    prewarm_task: asyncio.Task | None = None
    if os.environ.get("LEAKSHEET_PREWARM", "1") != "0":
        prewarm_task = asyncio.create_task(_prewarm_loop())
    yield
    # Shutdown: stop background work and close all three shared HTTP clients.
    if prewarm_task is not None:
        prewarm_task.cancel()
        # Awaiting our own cancelled task: its CancelledError is the expected
        # result, not a cancellation of this shutdown.
        with suppress(asyncio.CancelledError):
            await prewarm_task
    if _proxy_client is not None:
        await _proxy_client.aclose()
    await close_shared_client()
    await close_sheets_client()


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
_RATE_LIMIT_PATHS = ("/sheet", "/stream", "/metadata")
# /image-proxy is throttled in its OWN bucket at a much higher ceiling. Sharing
# the bucket above cost 25% of all cover art: one artist screen fires 40-120
# image requests in a burst, which drained the whole per-minute budget and
# 429'd the rest (131 of 521 requests in a single day's access log). It is also
# the least abusable of the four — disk-cached, 25MB download cap, 20MP decode
# cap, SSRF allowlist.
_IMAGE_RATE_LIMIT_MULTIPLIER = 10
# POST /cache/clear is the one privileged endpoint, and it was throttled by
# nothing: the guard above is opt-in via LEAKSHEET_RATE_LIMIT_PER_MIN, which is
# off by default, so token guessing was unbounded. This ceiling is fixed rather
# than derived from that variable — an operator flushing the cache does not
# approach it, and brute force must not depend on an optional setting.
_ADMIN_RATE_LIMIT_PER_MIN = 10
_RATE_LIMIT_WINDOW_S = 60.0
_rate_hits: dict[str, list[float]] = {}
_rate_last_prune = 0.0


def _client_ip(scope) -> str:
    """The address to bucket a request under.

    In prod the app sits behind a platform router, so ``scope["client"]`` is
    that router for EVERY request — bucketing on it puts the whole internet in
    one bucket and the limiter throttles all users at once. X-Forwarded-For
    fixes that but is caller-controlled, so it is only consulted when the
    operator states how many proxies to trust via
    ``LEAKSHEET_TRUSTED_PROXY_HOPS``: the value is counted from the RIGHT,
    which is the part a client cannot forge.
    """
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    try:
        hops = int(os.environ.get("LEAKSHEET_TRUSTED_PROXY_HOPS", "0") or 0)
    except ValueError:
        hops = 0
    if hops <= 0:
        return peer
    forwarded = Headers(scope=scope).get("x-forwarded-for", "")
    chain = [p.strip() for p in forwarded.split(",") if p.strip()]
    # Fewer entries than declared: the request didn't come through the
    # expected chain, so nothing in it is trustworthy.
    return chain[-hops] if len(chain) >= hops else peer


class _RateLimitMiddleware:
    """Opt-in sliding-window per-IP rate limiter (pure ASGI so it never buffers
    the streaming response body).

    Off by default — set ``LEAKSHEET_RATE_LIMIT_PER_MIN`` to a positive integer
    to cap requests-per-minute-per-IP on the expensive endpoints. Single-worker
    (see Dockerfile), so in-process counters are authoritative. The limit is read
    per request so it can be tuned without a redeploy.

    Behind a proxy, also set ``LEAKSHEET_TRUSTED_PROXY_HOPS`` — see
    :func:`_client_ip`, without which every caller shares one bucket.
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
        path = scope.get("path", "").rstrip("/")
        # Checked before the opt-in limit below, so the admin endpoint is
        # throttled even with LEAKSHEET_RATE_LIMIT_PER_MIN unset.
        if path.endswith("/cache/clear"):
            return self._over("|admin", _ADMIN_RATE_LIMIT_PER_MIN, scope)
        try:
            limit = int(os.environ.get("LEAKSHEET_RATE_LIMIT_PER_MIN", "0") or 0)
        except ValueError:
            limit = 0
        if limit <= 0:
            return False
        # Separate bucket + ceiling for image-proxy; see the constants above.
        if path.endswith("/image-proxy"):
            key_suffix, limit = "|img", limit * _IMAGE_RATE_LIMIT_MULTIPLIER
        elif any(path.endswith(p) for p in _RATE_LIMIT_PATHS):
            key_suffix = ""
        else:
            return False
        return self._over(key_suffix, limit, scope)

    def _over(self, key_suffix: str, limit: int, scope) -> bool:
        key = _client_ip(scope) + key_suffix
        now = time.monotonic()
        cutoff = now - _RATE_LIMIT_WINDOW_S
        hits = _rate_hits.setdefault(key, [])
        del hits[: bisect.bisect_right(hits, cutoff)]
        if len(hits) >= limit:
            return True
        hits.append(now)
        # After the append: the prune drops keys whose list is empty, and
        # running it first popped the entry `setdefault` had just created —
        # leaving `hits` an orphan, so that request went uncounted.
        self._maybe_prune(now, cutoff)
        return False

    @staticmethod
    def _maybe_prune(now: float, cutoff: float) -> None:
        global _rate_last_prune
        if now - _rate_last_prune <= _RATE_LIMIT_WINDOW_S:
            return
        _rate_last_prune = now
        for k in [k for k, v in _rate_hits.items() if not v or v[-1] < cutoff]:
            _rate_hits.pop(k, None)


app.add_middleware(_RateLimitMiddleware)

# CORS added last (outermost) — see docs/decisions.md::api.py::middleware-order
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sheets.safko.eu"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition", "ETag", "X-Cache-Status"],
)


# ---------------------------------------------------------------------------
# POST /api/sheet — parse a tracker URL → full Artist JSON
# ---------------------------------------------------------------------------

# A whole cold parse, every tab included. Per-request timeouts alone let a
# slow-drip host hold a parse (and everyone joined to it) indefinitely; this
# stays under Cloudflare's 125 s edge timeout so the client gets our message.
_PARSE_DEADLINE_S = 110.0

# Normalized tracker URL → the parse running for it: (task, progress listeners,
# the timer the parse reports into).
_parses: dict[str, tuple[asyncio.Task, list[Callable[[dict], None]], PhaseTimer]] = {}


async def _parse_once(
    url: str,
    *,
    cache_ttl: float,
    use_cache: bool,
    write_cache: bool,
    timer: PhaseTimer | None = None,
) -> tuple[Artist, asyncio.Task]:
    """Fetch and parse *url*, joining the parse already running for it if any.

    Returns the artist and the task warming its era covers, which starts once
    per parse. One parse per tracker at a time: a client retrying a stream it
    lost, a second device and the prewarm loop all used to start their own,
    and the box cannot fit two Ye-sized parses at once (README "Deployment").

    The first caller's cache flags decide. A joiner gets the same fresh parse
    its own flags would have produced from the cache miss that brought it here.
    Shielded, so a caller that goes away never cancels a parse others await.

    NEVER passes an artist name: the parse is written to a cache keyed by URL
    alone and shared with every other client, so a request-body field reaching
    it let anyone rename any tracker (and its slug, iOS favourites key
    material) for everyone. _parse_for_response applies the override to its
    own response only.
    """
    key = _normalize_url(url)
    entry = _parses.get(key)
    if entry is None:
        listeners: list[Callable[[dict], None]] = []

        def broadcast(event: dict) -> None:
            for listener in listeners:
                listener(event)

        shared = PhaseTimer(on_progress=broadcast)

        async def run() -> tuple[Artist, asyncio.Task]:
            async with asyncio.timeout(_PARSE_DEADLINE_S):
                artist = await async_fetch_and_parse(
                    url, artist_name=None, cache_ttl=cache_ttl,
                    use_cache=use_cache, write_cache=write_cache, timer=shared,
                )
            # Detached: covers download while the response is already on its
            # way. See _warm_era_art for why they must be fetched now.
            return artist, _spawn_detached(_warm_era_art(artist, url))

        entry = (asyncio.create_task(run()), listeners, shared)
        _parses[key] = entry
        entry[0].add_done_callback(
            lambda _task, mine=entry: _parses.pop(key) if _parses.get(key) is mine else None
        )

    task, listeners, shared = entry
    if timer is not None and timer.on_progress is not None:
        listeners.append(timer.on_progress)
    try:
        return await asyncio.shield(task)
    finally:
        if timer is not None:
            if timer.on_progress in listeners:
                listeners.remove(timer.on_progress)
            for name, seconds in shared.phases.items():
                timer.phases[name] = timer.phases.get(name, 0.0) + seconds


async def _background_revalidate(url: str) -> None:
    """Re-fetch and re-parse a tracker URL in the background to refresh cache.

    A revalidation already running for the URL is joined, not repeated. One
    that failed, or whose result the cache refused, is not retried for
    _REVALIDATE_BACKOFF_S: every stale hit used to start another full parse.
    """
    key = _normalize_url(url)
    if time.monotonic() < _revalidate_backoff.get(key, 0.0):
        return
    try:
        artist, warm = await _parse_once(url, cache_ttl=0, use_cache=True, write_cache=True)
        await asyncio.shield(warm)
        if artist._wire is None:
            _revalidate_backoff[key] = time.monotonic() + _REVALIDATE_BACKOFF_S
        logger.info("Background revalidation complete: %s", url[:80])
    except Exception as e:
        _revalidate_backoff[key] = time.monotonic() + _REVALIDATE_BACKOFF_S
        logger.warning("Background revalidation failed for %s: %s", url[:80], e)


# Per worker, like _parses. Keyed by normalized URL.
_REVALIDATE_BACKOFF_S = 15 * 60.0
_revalidate_backoff: dict[str, float] = {}


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
        await _background_revalidate(url)
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
            if server_etag:
                server_etag = _display_etag(server_etag, req.artist_name)
            if server_etag and server_etag == if_none_match:
                age = await async_get_cached_age(req.url)
                if age is not None and age < STALE_CACHE_TTL:
                    if age > DEFAULT_CACHE_TTL:
                        bg.add_task(_background_revalidate, req.url)
                    return Response(
                        status_code=304,
                        headers={
                            "ETag": f'"{server_etag}"',
                            "X-Cache-Status": "validated",
                            "Cache-Control": _CC_SHEET,
                            "Vary": "Accept",
                        },
                    )

    # Stale-while-revalidate fast path — see docs/decisions.md::api.py::swr-fast-path
    if use_cache:
        timer = PhaseTimer()
        with timer.phase("cache_read"):
            cached = await async_get_cached_parsed_bytes(req.url, max_age=STALE_CACHE_TTL)
        if cached is not None:
            raw, etag, age = cached
            if not etag:
                # Legacy cache entry without a stored hash. The ETag is a hash
                # of the served bytes, so this is one SHA-256 — no parse.
                with timer.phase("etag"):
                    etag = content_hash(raw)
            if req.artist_name:
                with timer.phase("rename"):
                    raw, etag = await asyncio.to_thread(_with_display_name, raw, etag, req.artist_name)
            is_stale = age > DEFAULT_CACHE_TTL

            if is_stale:
                bg.add_task(_background_revalidate, req.url)

            return Response(
                content=raw,
                media_type="application/json",
                headers={
                    "ETag": f'"{etag}"',
                    "X-Cache-Status": "stale" if is_stale else "hit",
                    "Cache-Control": _CC_SHEET,
                    "Vary": "Accept",
                    "Server-Timing": timer.server_timing_header(),
                },
            )

    # --- Cache miss: full fetch + parse ---
    # A client that sends Accept: application/x-ndjson gets the cold path as a
    # stream of real progress events followed by the artist. Hits, stale hits
    # and 304s above stay plain JSON for everyone: they are instant, and it
    # keeps ETag and cache semantics exactly as they were.
    if _NDJSON in request.headers.get("accept", ""):
        return _stream_sheet(req)

    timer = PhaseTimer()
    try:
        body, etag = await _parse_for_response(req, timer)
    except Exception as e:
        raise _sheet_http_error(req, e) from e
    logger.info("sheet_timing url=%s status=miss %s", req.url[:80], timer.log_line())
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "ETag": f'"{etag}"',
            "X-Cache-Status": "miss",
            "Cache-Control": _CC_SHEET,
            "Vary": "Accept",
            "Server-Timing": timer.server_timing_header(),
        },
    )


_NDJSON = "application/x-ndjson"


async def _parse_for_response(req: SheetRequest, timer: PhaseTimer) -> tuple[bytes, str]:
    """Cold-path parse for POST /sheet, as (response body, ETag).

    Shared by the JSON and NDJSON responses so the two cannot drift.
    """
    artist, _warm = await _parse_once(
        req.url,
        cache_ttl=0 if req.force_refresh else DEFAULT_CACHE_TTL,
        use_cache=req.use_cache and not req.force_refresh,
        # A force-refresh skips cache reads but must still repopulate it,
        # otherwise the next normal request pays another full cold fetch.
        write_cache=req.use_cache,
        timer=timer,
    )

    # The cache write already serialized this artist; serve those bytes.
    # Serialize only when there are none (use_cache false, or the collapse
    # guard refused the write) — off the event loop either way.
    wire = artist._wire
    if wire is None:
        with timer.phase("serialize"):
            wire = await asyncio.to_thread(serialize_artist, artist)
    if req.artist_name:
        with timer.phase("rename"):
            return await asyncio.to_thread(_with_display_name, *wire, req.artist_name)
    return wire


def _display_etag(etag: str, artist_name: str | None) -> str:
    """ETag of a response served under a caller's display name."""
    return content_hash(f"{etag}:{artist_name}".encode()) if artist_name else etag


def _with_display_name(raw: bytes, etag: str, artist_name: str) -> tuple[bytes, str]:
    """The cached payload renamed for one caller, and its ETag. Blocking.

    The shared cache always holds the page-inferred name (see _parse_once), so
    every path — cold, warm and 304 — applies the override the same way and
    derives the same ETag from the cached one. Applying it only on the cold
    path flipped the slug (iOS favourites key material) between requests.
    """
    tagged = _display_etag(etag, artist_name)
    data = json.loads(raw)
    slug = slugify(artist_name)
    if data.get("name") == artist_name and data.get("slug") == slug:
        return raw, tagged
    data["name"], data["slug"] = artist_name, slug
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(), tagged


def _sheet_http_error(req: SheetRequest, e: Exception) -> HTTPException:
    """Map a cold-path failure to the status and message a client sees.

    Messages are deliberately generic: several of these exceptions carry
    internal detail (resolved addresses, tried GIDs) that must stay in the log.
    """
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, InvalidURLError):
        return HTTPException(status_code=400, detail=f"Invalid URL: {e}")
    if isinstance(e, AccessDeniedError):
        # The provider's own wording ("401 Unauthorized", "410 Gone") means
        # nothing to a user staring at a tracker that used to work.
        logger.info("sheet access denied for %s", req.url[:120])
        return HTTPException(
            status_code=403,
            detail="This tracker is private or has been taken down.",
        )
    if isinstance(e, (httpx.InvalidURL, UnicodeError)):
        return HTTPException(status_code=400, detail="Invalid URL")
    if isinstance(e, TimeoutError):
        logger.warning("sheet parse exceeded %ss for %s", _PARSE_DEADLINE_S, req.url[:120])
        return HTTPException(status_code=503, detail="This tracker took too long to load. Please try again.")
    if isinstance(e, NetworkError):
        # NEVER interpolate: NetworkError wraps the SSRF guard's message,
        # which names the resolved address ("blocked non-public address
        # 10.0.0.5 for host …"). Same rule /stream and /image-proxy follow.
        logger.warning("sheet network error for %s: %s", req.url[:120], e)
        # 503, not 502: Cloudflare replaces an origin's 502 (and 504) with its
        # own error page, so this detail never reached a client in production.
        return HTTPException(status_code=503, detail="Could not reach the tracker source.")
    if isinstance(e, NoTablesError):
        # Carries the full GID list it tried — internal detail, not the user's.
        logger.warning("sheet has no table data at %s: %s", req.url[:120], e)
        return HTTPException(status_code=404, detail="No table data found at that URL.")
    if isinstance(e, (ParseError, ValueError)):
        logger.warning("sheet parse error for %s: %s", req.url[:120], e)
        return HTTPException(status_code=422, detail="Could not parse this tracker.")
    logger.error("Unhandled error during sheet parse: %s", e, exc_info=e)
    return HTTPException(status_code=500, detail="Internal error")


def _stream_sheet(req: SheetRequest) -> StreamingResponse:
    """The cold path as NDJSON: progress lines, then the artist.

    Every line is a JSON object except the last on success:

        {"type": "progress", "stage": "fetching", "message": "Found 19 tabs — downloading Unreleased"}
        {"type": "progress", "stage": "tabs", "message": "Read Misc", "done": 4, "total": 10}
        {"type": "artist", "etag": "…", "bytes": 11333206, "timing": "…"}
        <the artist JSON, exactly as POST /sheet returns it, on one line>

    or, on failure, a final {"type": "error", "status": 403, "detail": "…"}
    carrying the same status and message the JSON response would have. The
    artist follows its header as raw bytes rather than nested inside it, so an
    11 MB payload is never re-escaped; json.dumps never emits a literal
    newline, so it is exactly one line.

    GZipMiddleware compresses it: for a streaming body it sync-flushes every
    chunk, so each line still arrives as it happens, and it compresses chunks
    of 128 KiB and up (the artist line) off the event loop.
    """
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def emit(event: dict) -> None:
        queue.put_nowait(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")

    timer = PhaseTimer(on_progress=emit)

    async def run() -> None:
        try:
            body, etag = await _parse_for_response(req, timer)
            emit({
                "type": "artist",
                "etag": etag,
                "bytes": len(body),
                "timing": timer.server_timing_header(),
            })
            # Separately: `body + b"\n"` copied the whole multi-MB payload.
            queue.put_nowait(body)
            queue.put_nowait(b"\n")
            logger.info("sheet_timing url=%s status=miss stream %s", req.url[:80], timer.log_line())
        except Exception as e:
            err = _sheet_http_error(req, e)
            emit({"type": "error", "status": err.status_code, "detail": err.detail})
        finally:
            queue.put_nowait(None)

    # Detached from the response: if the client disconnects, the parse still
    # finishes and fills the cache.
    _spawn_detached(run())

    async def body_iter():
        while (item := await queue.get()) is not None:
            yield item

    headers = {
        "X-Cache-Status": "miss",
        "Cache-Control": "no-store",
        "Vary": "Accept",
        # nginx buffers upstream responses by default, which would hold every
        # progress line until the buffer filled.
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(body_iter(), media_type=_NDJSON, headers=headers)


# ---------------------------------------------------------------------------
# POST /cache/clear — clear the fetch cache (served as /api/cache/clear in prod)
# ---------------------------------------------------------------------------

@app.post("/cache/clear")
async def clear_fetch_cache(request: Request):
    """Clear the URL fetch cache (privileged).

    This mutates shared server state, so an unauthenticated endpoint would
    let anyone flush the cache and force cold refetches for everyone
    (CORS only gates browser JS, not direct requests). Requires the admin
    token: set
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
# The top bucket must stay above iPhone full-screen width. Why: docs/decisions.md.
_IMAGE_SIZE_BUCKETS = (128, 320, 640, 1280, 1600)
_IMAGE_CACHE_TTL = 7 * 86400          # resized results are valid for a week
_IMAGE_CACHE_MAX_BYTES = 200 * 1024 * 1024
_IMAGE_RESIZE_INPUT_CAP = 15 * 1024 * 1024  # don't decode >15MB on the 512MB box
# Concurrent Pillow decodes. Each can hold a 15MB input plus a 20MP decode
# (~80MB as RGBA), and an artist screen fires 40-120 image requests at once.
# At least 1: a Semaphore(0) would hang every resize forever.
_IMAGE_RESIZE_CONCURRENCY = max(1, int(os.environ.get("LEAKSHEET_IMAGE_RESIZE_CONCURRENCY") or 3))
_resize_sem: asyncio.Semaphore | None = None


def _resize_slot() -> asyncio.Semaphore:
    """Lazily created so the semaphore binds to the running loop."""
    global _resize_sem
    if _resize_sem is None:
        _resize_sem = asyncio.Semaphore(_IMAGE_RESIZE_CONCURRENCY)
    return _resize_sem
# Hard ceiling on what /image-proxy will pull into memory, checked while
# streaming so an oversized body is abandoned instead of buffered. Above the
# decode cap so a legitimately large source still reaches the resize path and
# fails there with a clear error rather than being silently truncated here.
_IMAGE_DOWNLOAD_CAP = 25 * 1024 * 1024
# Compressed-byte size says nothing about decoded size (a small, highly
# compressible image can unpack to hundreds of MB) — cap decoded pixels too,
# checked from the header before the full-frame load() below.
_IMAGE_MAX_DECODE_PIXELS = 20_000_000  # ~80MB peak as RGBA on the 512MB box

# Only lh3-lh6 accept arbitrary =sNNN sizing; lh7-rt 403s and
# docs.google.com/sheets-images 302s to login for N>0 (see web
# enhanceGoogleImageUrl) — those fall through to the Pillow path.
_GOOGLE_RESIZABLE_HOST_RE = re.compile(r"^lh[3-6]\.googleusercontent\.com$", re.IGNORECASE)
# Suffix grammar — see docs/decisions.md::api.py::google-size-suffix-regex
_GOOGLE_SIZE_SUFFIX_RE = re.compile(r"=[a-zA-Z]+\d*(-[a-zA-Z]+\d*)*$")


# Raster types only. image/svg+xml is a document that can carry script, and
# this proxy serves inline from the app's origin with ACAO *.
_RASTER_IMAGE_TYPES = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif",
    "image/avif", "image/heic", "image/heif", "image/bmp",
})


def _is_raster_image(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower() in _RASTER_IMAGE_TYPES


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
    hostname = urlparse(url).hostname or ""
    if not _GOOGLE_RESIZABLE_HOST_RE.match(hostname):
        return None
    return _GOOGLE_SIZE_SUFFIX_RE.sub("", url) + f"=s{w}"


def _image_cache_key(url: str, w: int | None) -> str:
    return hashlib.sha256(f"{url}|{w or 0}".encode()).hexdigest()


def _image_cache_paths(key: str):
    return CACHE_DIR / f"img_{key}.bin", CACHE_DIR / f"img_{key}.meta.json"


def _read_image_cache(key: str) -> tuple[bytes, str, str] | None:
    """Blocking read of a cached resized image — call via asyncio.to_thread.

    Returns (bytes, content_type, etag). The ETag is the one _write_image_cache
    stored. Entries written before it stored one fall back to the old
    key-plus-write-second form, which is what those clients were handed.
    """
    bin_path, meta_path = _image_cache_paths(key)
    try:
        meta = json.loads(meta_path.read_text())
        if time.time() - meta["timestamp"] > _IMAGE_CACHE_TTL:
            return None
        etag = meta.get("etag") or f"{key}-{int(meta['timestamp'])}"
        return bin_path.read_bytes(), meta["content_type"], etag
    except (OSError, ValueError, KeyError):
        return None


def _write_image_cache(key: str, data: bytes, content_type: str) -> str | None:
    """Blocking write + size-cap eviction — call via asyncio.to_thread.

    Returns the entry's ETag, so the response that just populated the cache
    advertises the SAME tag a later cache hit will — otherwise the first
    request's tag never matched and never 304'd.

    The tag is the key plus a digest of the bytes. The key alone is a hash of
    the REQUEST, so a post-TTL refetch with different content kept the same tag
    and a client holding the old bytes was told its copy was current. Mixing in
    the whole-second write time fixed that except within a second, and made the
    test for it sleep; the bytes themselves are what the tag must identify.
    """
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        bin_path, meta_path = _image_cache_paths(key)
        etag = f"{key}-{hashlib.sha256(data).hexdigest()[:16]}"
        meta_bytes = json.dumps({
            "content_type": content_type,
            "timestamp": time.time(),
            "etag": etag,
        }).encode()
        _atomic_write_bytes(bin_path, data)
        _atomic_write_bytes(meta_path, meta_bytes)
        _maybe_evict_image_cache()
        return etag
    except OSError as e:
        logger.warning("Image cache write failed: %s", e)
        return None


# A cover's Google URL is a one-time token: `sheets-images-rt/<token>` is
# reminted on every parse, so nothing in it is stable. Keying the image cache
# on it filed the same bytes under a fresh name every hour and left the LRU to
# evict the previous name — so a client holding a payload a few hours old asked
# for an entry that had been evicted, went upstream, and got Google's 403 on
# the expired token. That was 16% of all /image-proxy traffic on 2026-09-21.
#
# (tracker_url, era_name) IS stable, so derive a slot from it, store the bytes
# under the slot, and leave a tiny alias behind for every URL that has ever
# pointed at it. Old payloads keep resolving; one entry per era replaces one
# per era per parse.
def _era_art_base(tracker_url: str, era_name: str) -> str:
    """The stable cache identity of one era's cover, as a synthetic URL.

    Shaped like a URL so it drops straight into ``_image_cache_key`` and keeps
    the width-keyed thumbnail stable too — a resize is done once, not hourly.
    """
    tracker = hashlib.sha256(_normalize_url(tracker_url).encode()).hexdigest()[:32]
    era = hashlib.sha256(era_name.encode()).hexdigest()[:32]
    return f"leaksheet:art/{tracker}/{era}"


def _image_alias_path(url: str):
    return CACHE_DIR / f"imgalias_{hashlib.sha256(url.encode()).hexdigest()}.txt"


def _read_image_alias(url: str) -> str | None:
    """The stable base this URL was warmed under, if it was. Blocking."""
    try:
        base = _image_alias_path(url).read_text().strip()
    except OSError:
        return None
    # Only ever written by _write_image_alias. Guard anyway: this value becomes
    # a cache key, and a truncated write must not collide with a real entry.
    return base if base.startswith("leaksheet:art/") else None


def _write_image_alias(url: str, base: str) -> None:
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        _atomic_write_bytes(_image_alias_path(url), base.encode())
    except OSError as e:
        logger.warning("image alias write failed: %s", e)


def _touch_image_cache(key: str) -> bool:
    """True if *key* has a live entry, which is then marked recently used.

    Eviction drops the oldest mtime first. A cover the current parse still
    points at was otherwise dated to its first download and went before the
    copies left behind by later token refreshes.
    """
    bin_path, meta_path = _image_cache_paths(key)
    try:
        if time.time() - json.loads(meta_path.read_text())["timestamp"] > _IMAGE_CACHE_TTL:
            return False
        os.utime(bin_path)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


_IMAGE_EVICT_MIN_INTERVAL = 60.0  # scan the dir at most once a minute
_last_image_evict = 0.0


def _maybe_evict_image_cache() -> None:
    """Throttle the eviction scan.

    `_evict_image_cache` globs every `img_*.bin` and stats each one. Running
    that on EVERY cached image meant a full-directory scan per thumbnail — at
    200MB of ~50KB entries that is thousands of stats per write, on the one
    path an artist screen hits 40-120 times in a burst. Mirrors the identical
    throttle the sheet cache already uses (`_maybe_evict_sheet_cache`).
    """
    global _last_image_evict
    now = time.time()
    if now - _last_image_evict < _IMAGE_EVICT_MIN_INTERVAL:
        return
    _last_image_evict = now
    _evict_image_cache()


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


def _image_request_headers(url: str) -> dict[str, str]:
    # Matched on the parsed hostname, not as a substring of the whole URL:
    # "https://attacker.tld/?x=google.com" contains the string and was being
    # handed a docs.google.com Referer. _is_allowed_domain is the check this
    # file already uses correctly everywhere else.
    if _is_allowed_domain(url, set(), _GOOGLE_IMAGE_DOMAINS):
        return {"Referer": "https://docs.google.com/"}
    return {}


_ERA_ART_WARM_CONCURRENCY = 3
_background_tasks: set[asyncio.Task] = set()
def _spawn_detached(coro) -> asyncio.Task:
    """Run *coro* past the request that started it, keeping a reference so
    the task is not garbage-collected mid-flight."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _warm_era_art(artist, tracker_url: str) -> None:
    """Download each era cover now, while its URL still works, and keep it.

    See docs/decisions.md::api.py::_warm_era_art. Google's
    `sheets-images-rt` cover URLs carry a token that expires within minutes to
    tens of minutes, but a parse is served for hours and clients keep it for
    days — so covers loaded only while the parse was young. The original is
    stored in the image cache under the exact URL the payload carries (width
    0), which /image-proxy reads before going upstream.

    A URL that is already dead here (yetracker.net serves Cloudflare copies up
    to an hour old) keeps the era's last good cover.
    """
    covers: dict[str, str] = {}
    for era in artist.eras:
        url = era.art_url or ""
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith(("http://", "https://")) and _image_host_allowed(url):
            covers[era.name] = url
    if not covers:
        return

    slots = asyncio.Semaphore(_ERA_ART_WARM_CONCURRENCY)

    async def warm(era_name: str, url: str) -> None:
        # Keyed on (tracker, era), NOT on the URL — see _era_art_base. The
        # alias is what lets /image-proxy find this entry again when the client
        # asks for it under whatever token URL its own payload happens to hold.
        base = _era_art_base(tracker_url, era_name)
        key = _image_cache_key(base, None)
        await asyncio.to_thread(_write_image_alias, url, base)
        if await asyncio.to_thread(_touch_image_cache, key):
            return
        data, content_type = b"", ""
        async with slots:
            try:
                resp, data = await _get_image_capped(url, _image_request_headers(url))
                content_type = resp.headers.get("content-type", "")
            except (httpx.HTTPError, httpx.InvalidURL, HTTPException, ValueError) as exc:
                logger.info("era art warm: %s failed: %s", url[:80], exc)
        if not data:
            # The URL was already dead when we got here (yetracker.net serves
            # Cloudflare copies up to an hour old). Anything already under the
            # slot is this era's last good cover, so keep serving that.
            stored = await asyncio.to_thread(_read_image_cache, key)
            if not stored:
                return
            data, content_type = stored[0], stored[1]
        await asyncio.to_thread(_write_image_cache, key, data, content_type)

    await asyncio.gather(*(warm(name, url) for name, url in covers.items()))


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

    if not _image_host_allowed(url):
        raise HTTPException(status_code=403, detail="Domain not allowed for image proxy")

    width = _snap_image_width(w) if w else None
    base_headers = {
        "Cache-Control": _CC_IMAGE,
        # Deliberately wider than the app-wide CORS allowlist. Era colours are
        # extracted by reading proxied covers through a canvas, so the clients
        # request them with crossorigin="anonymous" (web/src/App.vue,
        # EraCard.vue) — and in local dev that request carries a localhost
        # Origin the allowlist does not name. What this can serve is bounded by
        # _image_host_allowed, re-checked after redirects, so the reach is
        # public tracker art and nothing else.
        "Access-Control-Allow-Origin": "*",
        # Served from the app's own origin: an image must never run script.
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }

    # The URL the client holds may be an expired cover token; the bytes are
    # filed under the (tracker, era) slot it was warmed into. Resolve that
    # first, so both the original and the width-keyed thumbnail are looked up
    # under a name that survives the next reparse. One small file read.
    cache_base = await asyncio.to_thread(_read_image_alias, url) or url

    # ETag scoped to disk cache — see docs/decisions.md::api.py::image-proxy-etag
    cache_key = None
    cached = None
    if width is not None:
        cache_key = _image_cache_key(cache_base, width)
        cached = await asyncio.to_thread(_read_image_cache, cache_key)
        if cached is not None:
            entry_etag = cached[2]
            base_headers["ETag"] = f'"{entry_etag}"'
            if _parse_if_none_match(request.headers.get("if-none-match", "")) == entry_etag:
                return Response(status_code=304, headers=base_headers)

    headers = _image_request_headers(url)

    try:
        if cached is not None:
            data, ct, _etag = cached
            return Response(
                content=data, media_type=ct,
                headers={**base_headers, "X-Cache-Status": "hit"},
            )

        # A cover downloaded by _warm_era_art while its token still worked.
        # Read before any upstream request (the URL may have expired since),
        # but after the thumbnail hit, which never needs the original.
        stored = await asyncio.to_thread(
            _read_image_cache, _image_cache_key(cache_base, None)
        )

        if width is not None:

            # Prefer Google-side resizing — no local decode, no disk cache
            # needed (the CDN did the work).
            google_url = _rewrite_google_size(url, width)
            if google_url is not None and stored is None:
                try:
                    # Capped, like the fallback path below. A plain .get() here
                    # buffered the whole body before the content-type check —
                    # the same shape that was "enough to OOM the worker" and
                    # prompted _get_image_capped, which was then only wired
                    # into the other branch.
                    resp, gdata = await _get_image_capped(google_url, headers)
                    ct = resp.headers.get("content-type", "")
                    if resp.status_code == 200 and _is_raster_image(ct):
                        return Response(
                            content=gdata, media_type=ct,
                            headers={**base_headers, "X-Cache-Status": "origin"},
                        )
                except httpx.HTTPError as exc:
                    # Fall through to the original URL + Pillow path.
                    logger.warning("image proxy: Google CDN resize failed for %s: %s", url[:80], exc)

        # Streamed with a byte cap rather than a plain .get(). A non-streaming
        # get() buffers the WHOLE body before the content-type check below,
        # and the size caps only apply inside _resize_image_bytes — i.e. after
        # the bytes are already resident, and only when `width` is given. The
        # allowlist admits any *.google.com host, including
        # drive.usercontent.google.com, so an arbitrarily large user-uploaded
        # file was enough to OOM the worker and drop every in-flight request.
        if stored is not None:
            data, ct = stored[0], stored[1]
            upstream_status = 200
        else:
            resp, data = await _get_image_capped(url, headers)
            ct = resp.headers.get("content-type", "")
            upstream_status = resp.status_code
        if upstream_status == 200 and _is_raster_image(ct):
            if width is not None:
                original_len = len(data)
                async with _resize_slot():
                    data, ct = await asyncio.to_thread(
                        _resize_image_bytes, data, width, ct
                    )
                # _resize_image_bytes returns the input untouched when it
                # refuses to decode (over _IMAGE_RESIZE_INPUT_CAP, over
                # _IMAGE_MAX_DECODE_PIXELS, or undecodable). Caching that under
                # the WIDTH-keyed entry filed a 20MB original as a thumbnail —
                # one entry being 10% of the 200MB budget, evicting real ones.
                if len(data) < original_len:
                    written_etag = await asyncio.to_thread(
                        _write_image_cache, cache_key, data, ct
                    )
                    if written_etag:
                        base_headers["ETag"] = f'"{written_etag}"'
                    status = "miss"
                else:
                    status = "origin"
            else:
                status = "origin"
            return Response(
                content=data, media_type=ct,
                headers={**base_headers, "X-Cache-Status": status},
            )

        # Never relay the upstream STATUS here: a non-image 200 (an error page,
        # an interstitial) turned into a 200 whose body was JSON, so <img> and
        # CachedImage saw success and rendered nothing — and heuristic caches
        # stored that as the image. 502 says "upstream gave us something we
        # can't serve", which is what happened.
        # 403 joins the 200 case rather than being relayed: Google answers 403
        # to an expired `sheets-images-rt` token, and that is us holding a
        # stale URL, not the caller being forbidden anything. Relaying it told
        # every client the cover was off-limits forever. 404 still passes
        # through — there the image really is gone.
        raise HTTPException(
            status_code=502 if upstream_status in (200, 403) else upstream_status,
            detail="Upstream image fetch failed",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Image proxy error: %s", e)
        raise HTTPException(status_code=502, detail="Image proxy error")


def _parse_content_length(raw: str | None) -> int | None:
    """Upstream Content-Length as an int, or None when absent or unusable.

    This used to be a bare int() sitting outside the try that guards the rest
    of proxy_stream, so a malformed header raised ValueError, returned 500, and
    leaked the streamed response — every other early exit in that handler
    aclose()s it. A length we cannot read is not a fatal condition: it only
    means the client gets no Content-Length.

    httpx joins repeated headers with ", ", so a duplicated Content-Length
    arrives as "123, 123". Identical values still describe one length;
    conflicting ones do not.
    """
    if not raw:
        return None
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    if len(parts) != 1:
        return None
    try:
        return int(parts.pop())
    except ValueError:
        return None


async def _get_image_capped(
    url: str, headers: dict[str, str]
) -> tuple[httpx.Response, bytes]:
    """GET *url*, reading at most `_IMAGE_DOWNLOAD_CAP` bytes.

    Returns the response and the body read so far. The body is only consumed
    for a 200 image/*; anything else is abandoned unread, so an error page or
    a huge non-image never lands in memory. Mirrors the stream-and-stop shape
    of `streaming._get_text_capped`.
    """
    req = _get_proxy_client().build_request("GET", url, headers=headers)
    resp = await _get_proxy_client().send(req, stream=True)

    # The allowlist was checked on the URL we were GIVEN. follow_redirects=True
    # means an allow-listed host can still 30x anywhere, so re-check the url we
    # LANDED on. PublicOnlyAsyncTransport already refuses private targets at
    # connect time, which is why this is an allowlist check and not
    # assert_public_redirect_target: that one re-resolves the host over DNS to
    # redo work the transport has done, and the image proxy serves dozens of
    # thumbnails per screen.
    #
    # Runs before any body byte is read, so nothing off-host is ever relayed.
    final_url = str(resp.url)
    if final_url != url and not _image_host_allowed(final_url):
        await resp.aclose()
        logger.warning("image proxy: redirect off allowlist -> %s", final_url[:120])
        raise HTTPException(status_code=502, detail="Upstream redirect not allowed")
    try:
        ct = resp.headers.get("content-type", "")
        if resp.status_code != 200 or not _is_raster_image(ct):
            return resp, b""

        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > _IMAGE_DOWNLOAD_CAP:
                raise HTTPException(status_code=502, detail="Upstream image too large")
            chunks.append(chunk)
        return resp, b"".join(chunks)
    finally:
        await resp.aclose()


# ---------------------------------------------------------------------------
# GET /api/metadata — fetch audio file metadata from provider APIs
# ---------------------------------------------------------------------------

_METADATA_USER_AGENT = USER_AGENT  # shared backend UA from src.config

# Provider metadata rarely changes for a given file — cache parsed results so
# repeated description-sheet opens don't re-hit provider APIs.
# TTLCache lives in src.streaming (the lower-level module) so the CDN-resolve
# cache there can use the same primitive.
_metadata_cache = TTLCache(ttl=3600.0, max_entries=500)


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


# Codec regex rationale — see docs/decisions.md::api.py::video-codec-regex
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
    # The live API returns the mime under "type"; "mimeType" is accepted too
    # because the old tests pinned that spelling and it may be a legacy form.
    # Reading only "mimeType" meant every real response lost its mime and
    # reported media_kind "unknown", so video files never got a video surface.
    mime = data.get("type") or data.get("mimeType")
    if data.get("size"):
        result["file_size"] = data["size"]
    if mime:
        result["mime_type"] = mime
    if data.get("name"):
        result["filename"] = data["name"]
    result["media_kind"] = _media_kind_from_mime(mime)
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
# GET /api/trackers — artist tracker discovery from the ArtistGrid registry
# ---------------------------------------------------------------------------


_trackers_cache = TTLCache(ttl=3600.0, max_entries=1)
# Last successful payload, kept indefinitely as a fallback for upstream errors.
_trackers_stale: str | None = None
# Suppress upstream retries for this long after a failure — see list_trackers.
_TRACKERS_FAIL_BACKOFF_S = 60.0
_trackers_fail_until = 0.0

# Built-in fallback (see src/tracker_seed.py) — served when ArtistGrid can't
# be fetched and no live payload has ever succeeded, so /trackers never hard-fails.
_SEED_PAYLOAD = json.dumps([
    TrackerEntry(name=name, url=url).model_dump() for name, url in SEED_TRACKERS
])


@app.get("/health")
async def health() -> Response:
    """Liveness probe for the container HEALTHCHECK.

    Deliberately does no I/O — it answers "the event loop is running and can
    serve a request", which is exactly what the watchdog needs to know. The
    probe used to hit /docs, which rendered the whole Swagger page and tied
    liveness to docs staying enabled.
    """
    return Response(
        content='{"status":"ok"}',
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/trackers")
async def list_trackers():
    """List artist trackers from the ArtistGrid registry CSV (cached 1h).

    Falls back to the last successful fetch, or if there's none yet, to the
    built-in seed list (src/tracker_seed.py) — see X-Cache-Status.
    """
    global _trackers_stale, _trackers_fail_until

    # Back off after a failure. Only SUCCESS populated the cache, so during an
    # ArtistGrid outage every single request re-hit upstream — the endpoint is
    # also outside the rate limiter, so a burst of clients turned one outage
    # into sustained amplification against a third party.
    if time.monotonic() < _trackers_fail_until:
        return _trackers_fallback_response()

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

    try:
        # Also registers every listed tracker's host — this is the warm path
        # for the /sheet allowlist (see config.sheet_host_allowed).
        entries = await fetch_artistgrid_entries()
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
        logger.exception("ArtistGrid fetch failed: %s", e)
        _trackers_fail_until = time.monotonic() + _TRACKERS_FAIL_BACKOFF_S
        return _trackers_fallback_response()


def _trackers_fallback_response() -> Response:
    """Last good fetch if we have one, else the built-in seed list."""
    if _trackers_stale is not None:
        return Response(
            content=_trackers_stale,
            media_type="application/json",
            headers={
                "Cache-Control": _CC_TRACKERS_STALE,
                "X-Cache-Status": "stale",
            },
        )
    return Response(
        content=_SEED_PAYLOAD,
        media_type="application/json",
        headers={
            "Cache-Control": _CC_TRACKERS_STALE,
            "X-Cache-Status": "seed",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/stream — proxy audio (CORS bypass) with range request support
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _RangePlan:
    """Decision for serving a client Range when upstream ignored it.

    kind:
      'full'          — serve the whole body as HTTP 200 (no/ignored Range)
      'partial'       — synthesise HTTP 206 for bytes [start, end]
      'unsatisfiable' — HTTP 416 with Content-Range: bytes */total
    """

    kind: str
    start: int = 0
    end: int | None = None


# Digit runs are BOUNDED. Python >= 3.11 (the production image) caps
# string->int at 4300 digits and raises ValueError past it, and the int() calls
# on these captures sit outside the /stream try block — so an unbounded `\d+`
# turned a crafted Range header into an uncaught 500. 19 digits covers any
# real offset (max int64 is 19).
_RANGE_SPEC = re.compile(r"^bytes=(?:(\d{1,19})-(\d{0,19})|-(\d{1,19}))$")

# Discarding more than this to synthesise a 206 is worth a log line.
_DISCARD_WARN_BYTES = 8 * 1024 * 1024


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
    if total_size is None:
        # We can't clamp, so we can't promise a Content-Length. Serving the
        # full body signals "Range unsupported"; a synthesised 206 here
        # advertised the client's requested length (`bytes=0-999999999` →
        # Content-Length: 1000000000) and then delivered a much shorter body.
        # Same reasoning as the suffix and open-ended branches above.
        return _RangePlan("full")
    end = min(end, total_size - 1)
    return _RangePlan("partial", start, end)


async def _slice_byte_stream(source, range_start: int, range_end: int):
    """Yield only bytes [range_start, range_end] (inclusive) from a chunked stream.

    Used to synthesise HTTP 206 responses when the upstream host ignores
    Range requests. Stops consuming the source once the range is served.

    Everything before `range_start` is downloaded and thrown away — a seek into
    the middle of a large file costs that many bytes of upstream traffic. Hosts
    that honour Range never reach here; the ones that don't are logged below so
    the cost stops being invisible.
    """
    if range_start > _DISCARD_WARN_BYTES:
        logger.warning(
            "Synthesising a 206 by discarding %.1f MB of upstream body — "
            "this host ignores Range",
            range_start / 1_048_576,
        )
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

    if not _is_allowed_domain(stream_url, ALLOWED_STREAM_HOSTS):
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
        _rs_m = re.match(r"bytes=(\d{1,19})-", range_header)
        if _rs_m:
            _range_start = int(_rs_m.group(1))
        else:
            _is_suffix_range = bool(re.match(r"bytes=-\d+", range_header))

    try:
        resp = await stream_audio(stream_url, range_header=range_header)
    except GdriveInterstitialError as e:
        # Never proxy HTML as audio — see docs/decisions.md::api.py::gdrive-interstitial
        logger.warning("gdrive interstitial for %s: %s", stream_url, e)
        raise HTTPException(status_code=409, detail="gdrive_interstitial")
    except UpstreamStatusError as e:
        # Relay what upstream actually said, so a client can tell "this file is
        # gone" from "the host is throttling us". Everything else stays 502.
        # Only the status code crosses over — see UpstreamStatusError.
        logger.warning("Stream upstream %s for %s", e.status_code, stream_url)
        if e.status_code in (404, 410):
            raise HTTPException(status_code=404, detail="Upstream file not found")
        if e.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="Upstream rate limited",
                headers={"Retry-After": "30"},
            )
        raise HTTPException(status_code=502, detail="Upstream error")
    except ValueError as e:
        # The message names internal hosts and SSRF-check internals (a DNS
        # failure surfaced as "imgur.gg cdnUrl host does not resolve:
        # i.imgur.gg" to the client). Log it; return something generic.
        logger.warning("Stream error for %s: %s", stream_url, e)
        raise HTTPException(status_code=502, detail="Upstream error")
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
    total_size = _parse_content_length(resp.headers.get("content-length"))

    # MIME sniffing on first chunk — see docs/decisions.md::api.py::mime-sniffing
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
            # Bounded digits: int() refuses >4300, which was a 500 and a leaked response.
            cr_match = re.match(r"bytes (\d{1,18})-(\d{1,18})/", cr)
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
        # 200-not-206 fallback — see docs/decisions.md::api.py::range-fallback
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
    # A 'partial' plan is only made when total_size is known.
    partial_headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": ct or "application/octet-stream",
        "Content-Length": str(content_length),
        "Content-Range": f"bytes {range_start}-{range_end}/{total_size}",
    }
    if _disposition:
        partial_headers["Content-Disposition"] = _disposition
    return StreamingResponse(
        _closing(_slice_byte_stream(_iter_upstream(), range_start, range_end)),
        status_code=206,
        headers=partial_headers,
        media_type=ct or "application/octet-stream",
    )
