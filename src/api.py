"""LeakSheet — FastAPI HTTP layer.

Endpoints:
  POST /sheet       — send a tracker URL, get parsed Artist JSON back
                      (ETag / stale-while-revalidate)
  GET  /trackers    — ArtistGrid discovery list, best-first
  GET  /stream      — proxy audio/video from supported file hosts (Range support)
  GET  /image-proxy — proxy images through backend (width buckets, disk cache)
  GET  /metadata    — file metadata from provider APIs (incl. media_kind)
  GET  /hosts       — which stream providers are down right now
  GET  /health      — liveness, no I/O
  POST /cache/clear — clear the URL fetch cache (admin: X-Admin-Token)

In production nginx serves these under /api/* and strips the prefix.
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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.datastructures import Headers
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from src.config import (
    ARTISTGRID_URL,
    USER_AGENT,
    VERSION,
    _IMAGE_ALLOWED_DOMAINS,  # noqa: F401 — re-exported for tests
    _IMAGE_ALLOWED_PARENT_DOMAINS,  # noqa: F401
    _image_host_allowed,
    _is_allowed_domain,
)
from src import host_health
from src.models import Artist, TrackerEntry, slugify
from src.tracker_seed import SEED_TRACKERS
from src.fetcher import (
    AccessDeniedError,
    CACHE_DIR,
    _era_art_base,
    read_art_pointer,
    _SAME_ART_MAX_DISTANCE,
    _dhash,
    update_art_pointer,
    _atomic_write_bytes,
    _normalize_url,
    async_fetch_and_parse,
    async_get_cached_age,
    async_get_cached_etag,
    async_get_cached_parsed_bytes,
    clear_cache,
    close_sheets_client,
    drop_cached_entry,
    fetch_artistgrid_entries,
    serialize_artist,
    content_hash,
    DEFAULT_CACHE_TTL,
    InvalidURLError,
    MAX_DECODE_PIXELS,
    NetworkError,
    NoTablesError,
    ParseError,
    PhaseTimer,
    SERVE_STALE_TTL,
    SignedOutError,
    SourceGoneError,
    unlink_if_older,
)
from src.streaming import (
    get_capped,
    ALLOWED_STREAM_HOSTS,
    GdriveInterstitialError,
    NonMediaError,
    PublicOnlyAsyncTransport,
    TTLCache,
    UpstreamStatusError,
    close_shared_client,
    resolve_metadata_url,
    resolve_stream_url,
    stream_audio,
    _get_shared_client,
)

# gunicorn's UvicornWorker installs no logging config: without this the root logger stays
# at WARNING and every INFO line (sheet_timing, cover matching) is dropped.
logging.basicConfig(format="%(levelname)s %(name)s pid=%(process)d %(message)s")  # docker adds the time
logging.getLogger().setLevel(os.environ.get("LEAKSHEET_LOG_LEVEL", "INFO").upper())
# One line per upstream or client request would drown the rest; nginx logs requests.
for _noisy in ("httpx", "httpcore", "uvicorn.access"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# Media types and metadata tags used in several places.
_MIME_MP4 = "audio/mp4"
_MIME_OGG = "audio/ogg"
_MIME_FLAC = "audio/flac"
_MIME_WAV = "audio/wav"
_MIME_MPEG = "audio/mpeg"
_MIME_OCTET = "application/octet-stream"
_MIME_JSON = "application/json"
_UNEXPECTED_HEAD = "unexpected payload head"
_UPSTREAM_ERROR = "Upstream error"
_TAG_CODEC_PROFILE = "CODEC PROFILE"
_TAG_SAMPLE_RATE = "SAMPLE RATE"
_TAG_BITS = "BITS PER SAMPLE"
_TAG_CHANNELS = "NUMBER OF CHANNELS"


# Secrets this process holds. Frame locals are scrubbed only by variable name, so these
# are also replaced by value anywhere in an event or log line.
_SECRET_ENV = ("LEAKSHEET_GOOGLE_API_KEY", "LEAKSHEET_ADMIN_TOKEN")


def _redact(value, secrets: list[str]):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[Filtered]")
        return value
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, secrets) for v in value]
    return value


def _scrub_secrets(payload: dict, _hint: dict) -> dict:
    # Short values would blank unrelated text; real keys and tokens are long.
    secrets = [v for name in _SECRET_ENV if len(v := os.environ.get(name, "").strip()) >= 8]
    return _redact(payload, secrets) if secrets else payload


def _sentry_options(dsn: str) -> dict:
    """GlitchTip settings: errors and INFO+ log lines, no request PII.

    No HTTP status is an issue by itself: 5xx answers here are upstream outages, logged
    where they happen, and an unhandled exception still reaches GlitchTip as one.
    """
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

    return dict(
        dsn=dsn,
        release=f"leaksheet-api@{VERSION}",
        enable_logs=True,
        traces_sample_rate=0.0,
        send_default_pii=False,
        # send_default_pii=False scrubs X-Forwarded-For but not Cloudflare's IP headers.
        event_scrubber=EventScrubber(
            denylist=DEFAULT_DENYLIST + ["cf-connecting-ip", "true-client-ip", "x-admin-token", "x-goog-api-key"]
        ),
        before_send=_scrub_secrets,
        before_send_log=_scrub_secrets,
        integrations=[
            StarletteIntegration(failed_request_status_codes=set()),
            FastApiIntegration(failed_request_status_codes=set()),
        ],
    )


if _sentry_dsn := os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    from sentry_sdk.integrations.logging import ignore_logger_for_sentry_logs

    # Worker boot, recycle and shutdown lines stay on stdout only.
    for _server_logger in ("uvicorn.error", "gunicorn.error"):
        ignore_logger_for_sentry_logs(_server_logger)
    sentry_sdk.init(**_sentry_options(_sentry_dsn))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MIME type corrections — upstream hosts sometimes send non-standard types
# that iOS Safari / WebKit rejects as "source not supported".
# ---------------------------------------------------------------------------

_MIME_CORRECTIONS: dict[str, str] = {
    # audio/m4a, audio/x-m4a are not registered IANA types; Safari needs audio/mp4
    "audio/m4a": _MIME_MP4,
    "audio/m4b": _MIME_MP4,
    "audio/x-m4a": _MIME_MP4,
}

# Audio format sniffing — see docs/decisions.md::api.py::mime-sniffing

# Files a tracker link can point at that are never playable: see
# docs/decisions.md::api.py::non-media-415.
_NON_MEDIA_SIGNATURES = (b"%PDF", b"PK\x03\x04", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"Rar!", b"7z\xbc\xaf")


def _is_non_media(head: bytes) -> bool:
    if head.startswith(_NON_MEDIA_SIGNATURES):
        return True
    return head.lstrip()[:9].lower().startswith((b"<!doctype", b"<html"))


def _sniff_audio_format(header: bytes) -> str | None:
    """Detect audio format from magic bytes.  Returns corrected MIME or None."""
    if not header:
        return None

    # Ogg container (Vorbis, Opus, FLAC-in-Ogg) — "OggS"
    if header[:4] == b"OggS":
        return _MIME_OGG
    # Partial Ogg: a short read (Safari's bytes=0-1 probe) that is a genuine prefix of
    # "OggS", not any byte starting 'O', which would misclassify tiny bodies.
    if 0 < len(header) < 4 and b"OggS".startswith(header):
        return _MIME_OGG

    # FLAC — "fLaC"
    if header[:4] == b"fLaC":
        return _MIME_FLAC

    # WAV — "RIFF....WAVE"
    if header[:4] == b"RIFF" and (len(header) < 12 or header[8:12] == b"WAVE"):
        return _MIME_WAV

    # MP3 — ID3 tag header
    if header[:3] == b"ID3":
        return _MIME_MPEG

    # MP3 — raw sync frame (0xFF 0xEx or 0xFF 0xFx)
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return _MIME_MPEG

    # MP4 / M4A — standard ftyp box at offset 4
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return _MIME_MP4

    # Other MP4 boxes at offset 4 (moov, mdat, free, skip, wide)
    if len(header) >= 8 and header[4:8] in _MP4_BOXES:
        return _MIME_MP4

    return None

_MP4_BOXES = {b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot"}

# Enough for every signature above (WAVE needs 12) and the head of an HTML page.
_SNIFF_BYTES = 16

# Map file extensions to MIME types — used to resolve generic upstream types
# (application/octet-stream) when the URL contains a recognisable extension.
_EXT_TO_MIME: dict[str, str] = {
    ".m4a": _MIME_MP4,
    ".m4b": _MIME_MP4,
    ".mp3": _MIME_MPEG,
    ".ogg": _MIME_OGG,
    ".oga": _MIME_OGG,
    ".flac": _MIME_FLAC,
    ".aac": "audio/aac",
    ".wav": _MIME_WAV,
}

# Map corrected MIME types to file extensions for Content-Disposition
_MIME_TO_EXT: dict[str, str] = {
    _MIME_MP4: ".m4a",
    _MIME_MPEG: ".mp3",
    _MIME_OGG: ".ogg",
    _MIME_WAV: ".wav",
    _MIME_FLAC: ".flac",
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
    1. Content-Disposition filename extension (file hosts include the real
       filename even when the URL path has none, e.g. api.pillows.su/api/get/{id}).
    2. URL path extension (works when upstream redirects to a CDN URL with ext).
    3. Fall back to audio/mpeg.

    Safari strictly validates Content-Type, so m4a served as audio/mpeg fails.
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
    if base in (_MIME_OCTET, "binary/octet-stream", ""):
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
        return _MIME_MPEG

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

# Single source of truth: the hosts resolve_stream_url can emit.


# Google image CDNs, for the Referer decision below. Parent domains: a
# subdomain of any of these counts.
_GOOGLE_IMAGE_DOMAINS = {
    "googleusercontent.com", "ggpht.com", "google.com", "gstatic.com",
}


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
            # SSRF guard: refuse non-public hosts on every hop, so an allow-listed image
            # URL that redirects to an internal address is refused at connect.
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

    Gzip drops Content-Length on a streaming body, which breaks audio duration and
    Range seeking on iOS Safari (Range offsets refer to the raw bytes).
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
    prober = asyncio.create_task(host_health.probe_forever())
    yield
    prober.cancel()
    # Shutdown: close all three shared HTTP clients.
    if _proxy_client is not None:
        await _proxy_client.aclose()
    await close_shared_client()
    await close_sheets_client()


app = FastAPI(
    title="LeakSheet",
    description="Parser + API for Google Spreadsheet-based music tracker documents",
    version=VERSION,
    lifespan=lifespan,
    # nginx serves the API under /api/, so the default docs UI never loaded its schema.
    openapi_url=None,
)

# compresslevel 6 ≈ level 9's ratio on JSON at a fraction of the CPU.
app.add_middleware(_StreamSafeGZipMiddleware, minimum_size=1000, compresslevel=6)


# Expensive endpoints worth throttling: cold sheet fetches and the upstream
# proxies. Cheap/cached endpoints (/trackers) are left alone.
_RATE_LIMIT_PATHS = ("/sheet", "/stream", "/metadata")
# /image-proxy gets its OWN bucket at a higher ceiling: one artist screen bursts
# 40-120 image requests, and the endpoint is disk-cached and size-capped.
_IMAGE_RATE_LIMIT_MULTIPLIER = 10
# Fixed admin ceiling, independent of the opt-in LEAKSHEET_RATE_LIMIT_PER_MIN, so
# token brute force is always throttled.
_ADMIN_RATE_LIMIT_PER_MIN = 10
_RATE_LIMIT_WINDOW_S = 60.0
_rate_hits: dict[str, list[float]] = {}
_rate_last_prune = 0.0


def _client_ip(scope) -> str:
    """The address to bucket a request under.

    X-Forwarded-For is consulted only when LEAKSHEET_TRUSTED_PROXY_HOPS is set,
    counted from the right: see docs/decisions.md::api.py::_client_ip.
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

    Off unless ``LEAKSHEET_RATE_LIMIT_PER_MIN`` is a positive integer (read per
    request). Counters are per worker process, so the effective limit is up to
    workers x the setting; Cloudflare's rate rule on /api/sheet is the real limit.
    Behind a proxy, also set ``LEAKSHEET_TRUSTED_PROXY_HOPS`` (see :func:`_client_ip`).
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
        # After the append: pruning first would pop the entry `setdefault` just created,
        # leaving this request uncounted.
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

# Bounds a whole cold parse, every tab included, so a slow-drip host can't hold it
# (and every joiner) forever. Stays under Cloudflare's 125 s edge timeout.
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

    Returns the artist and the task warming its era covers. One parse per
    tracker per worker process. The first caller's cache flags decide; shielded,
    so a caller that goes away never cancels a parse others await.

    NEVER passes an artist name: the parse is cached by URL alone and shared, so
    a request field reaching it would rename the tracker for everyone.
    _parse_for_response applies the override to its own response only.
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
            timer.tabs.update(shared.tabs)
            timer.api_tabs_asked += shared.api_tabs_asked
            timer.api_tabs_served += shared.api_tabs_served


async def _background_revalidate(url: str) -> None:
    """Re-fetch and re-parse a tracker URL in the background to refresh cache.

    A revalidation already running for the URL is joined, not repeated. One
    that failed, or whose result the cache refused, is not retried for
    _REVALIDATE_BACKOFF_S.
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
        # Gone or signed-out at the source: a stale copy must not outlive it (serve-stale-window).
        # A plain 403 may be a challenge page or a blip, so it keeps the copy.
        if isinstance(e, (SignedOutError, SourceGoneError)):
            try:
                await asyncio.to_thread(drop_cached_entry, url)
            except OSError:
                logger.exception("Could not drop the cached entry for %s", url[:80])


# Per worker, like _parses. Keyed by normalized URL.
_REVALIDATE_BACKOFF_S = 15 * 60.0
_revalidate_backoff: dict[str, float] = {}


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


def _sheet_headers(etag: str, status: str, timer: PhaseTimer | None = None) -> dict[str, str]:
    headers = {
        "ETag": f'"{etag}"',
        "X-Cache-Status": status,
        "Cache-Control": _CC_SHEET,
        "Vary": "Accept",
    }
    if timer is not None:
        headers["Server-Timing"] = timer.server_timing_header()
    return headers


async def _validated_304(req: SheetRequest, request: Request, bg: BackgroundTasks) -> Response | None:
    """The ETag-based 304 fast path."""
    if_none_match = _parse_if_none_match(request.headers.get("if-none-match", ""))
    server_etag = await async_get_cached_etag(req.url) if if_none_match else None
    if not server_etag or _display_etag(server_etag, req.artist_name) != if_none_match:
        return None
    age = await async_get_cached_age(req.url)
    if age is None or age >= SERVE_STALE_TTL:
        return None
    if age > DEFAULT_CACHE_TTL:
        bg.add_task(_background_revalidate, req.url)
    return Response(status_code=304, headers=_sheet_headers(if_none_match, "validated"))


async def _cached_sheet(req: SheetRequest, bg: BackgroundTasks) -> Response | None:
    """Stale-while-revalidate fast path — see docs/decisions.md::api.py::swr-fast-path"""
    timer = PhaseTimer()
    with timer.phase("cache_read"):
        cached = await async_get_cached_parsed_bytes(req.url, max_age=SERVE_STALE_TTL)
    if cached is None:
        return None
    raw, etag, age = cached
    if req.artist_name:
        with timer.phase("rename"):
            raw, etag = await asyncio.to_thread(_with_display_name, raw, etag, req.artist_name)
    is_stale = age > DEFAULT_CACHE_TTL
    if is_stale:
        bg.add_task(_background_revalidate, req.url)
    return Response(
        content=raw, media_type=_MIME_JSON, headers=_sheet_headers(etag, "stale" if is_stale else "hit", timer),
    )


@app.post("/sheet", responses={
    400: {"description": "Bad Request"},
    404: {"description": "Not Found"},
    503: {"description": "Service Unavailable"},
})
async def parse_sheet(
    req: SheetRequest,
    request: Request,
    bg: BackgroundTasks,
):
    """Fetch and parse a tracker spreadsheet.

    Supports ETag-based conditional requests (If-None-Match header) and
    stale-while-revalidate: cached data up to 7 days old is served instantly
    (a matching ETag gets a 304) while a background refresh is triggered once
    it is over an hour old. Older data is a cold parse. A refresh that finds the
    source gone or private deletes the cached entry.
    """
    use_cache = req.use_cache and not req.force_refresh
    # Up front: every path below normalizes the URL, and an invalid one must be a
    # 400, not a 500 out of the cache lookups.
    try:
        _normalize_url(req.url)
    except InvalidURLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid URL: {e}") from e
    if use_cache:
        cached = await _validated_304(req, request, bg) or await _cached_sheet(req, bg)
        if cached is not None:
            return cached

    # --- Cache miss: full fetch + parse ---
    # Accept: application/x-ndjson streams progress events, then the artist. Hits,
    # stale hits and 304s stay plain JSON: they are instant.
    if _NDJSON in request.headers.get("accept", ""):
        return _stream_sheet(req)
    timer = PhaseTimer()
    try:
        body, etag = await _parse_for_response(req, timer)
    except Exception as e:
        raise _sheet_http_error(req, e) from e
    logger.info("sheet_timing url=%s status=miss %s", req.url[:80], timer.log_line())
    return Response(content=body, media_type=_MIME_JSON, headers=_sheet_headers(etag, "miss", timer))


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
    if not artist.total_versions:
        failed, total = timer.tab_counts()
        # A loaded content tab cannot vouch for song tabs that did not load.
        if failed or not any(t.entries for t in artist.tabs):
            # Never cached (cache-collapse-guard): a 200 would put an empty tracker in the app.
            logger.warning("sheet parsed empty for %s: failed_tabs=%d/%d", req.url[:120], failed, total)
            if failed:
                raise HTTPException(status_code=503, detail="This tracker's tabs did not load. Please try again.")
            raise HTTPException(status_code=404, detail="No songs found in this tracker.")

    # Serve the bytes the cache write already serialized; serialize (off the event
    # loop) only when there are none: use_cache false, or the collapse guard refused.
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


def _leading_name_and_slug(head: str) -> tuple[tuple[str, str], int]:
    """(name, slug) from the start of a payload, and where the slug ends.

    Raises ValueError unless the object opens with exactly those two keys.
    """
    if not head.startswith("{"):
        raise ValueError(_UNEXPECTED_HEAD)
    decoder = json.JSONDecoder()
    values = []
    i = 0
    for key in ("name", "slug"):
        i = _skip_json_ws(head, i + 1)  # past "{" or ","
        found, i = decoder.raw_decode(head, i)
        i = _skip_json_ws(head, i)
        if found != key or head[i:i + 1] != ":":
            raise ValueError(_UNEXPECTED_HEAD)
        value, i = decoder.raw_decode(head, _skip_json_ws(head, i + 1))
        values.append(value)
        i = _skip_json_ws(head, i)
        if head[i:i + 1] != ",":
            raise ValueError(_UNEXPECTED_HEAD)
    return (values[0], values[1]), i


def _skip_json_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\n\r":
        i += 1
    return i


def _with_display_name(raw: bytes, etag: str, artist_name: str) -> tuple[bytes, str]:
    """The cached payload renamed for one caller, and its ETag. Blocking.

    The shared cache always holds the page-inferred name (see _parse_once), so
    cold, warm and 304 paths apply the override the same way and derive the same
    ETag, keeping the slug (iOS favourites key material) stable.
    """
    tagged = _display_etag(etag, artist_name)
    slug = slugify(artist_name)
    # The payload opens with name then slug (Artist field order): splice those two
    # rather than round-tripping a multi-MB document through json on every warm hit.
    head = raw[:4096].decode("utf-8", errors="ignore")
    try:
        (name, old_slug), end = _leading_name_and_slug(head)
    except ValueError:
        data = json.loads(raw)
        data["name"], data["slug"] = artist_name, slug
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(), tagged
    if (name, old_slug) == (artist_name, slug):
        return raw, tagged
    rest = raw[len(head[:end].encode("utf-8")):]
    new_head = f'{{"name": {json.dumps(artist_name, ensure_ascii=False)}, "slug": {json.dumps(slug, ensure_ascii=False)}'
    return new_head.encode("utf-8") + rest, tagged


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
        # NEVER interpolate: NetworkError wraps the SSRF guard's message, which names the
        # resolved address. Same rule /stream and /image-proxy follow.
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
            # Newline queued separately: `body + b"\n"` would copy the multi-MB payload.
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

@app.post("/cache/clear", responses={
    401: {"description": "Unauthorized"},
    503: {"description": "Service Unavailable"},
})
async def clear_fetch_cache(request: Request):
    """Clear the URL fetch cache (privileged).

    Requires ``LEAKSHEET_ADMIN_TOKEN``, sent as the ``X-Admin-Token`` header. With
    the token unset the endpoint is disabled (fail closed: behind a reverse proxy
    the client IP is the proxy, so loopback checks aren't trustworthy).
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
# See docs/decisions.md::api.py — image width buckets
_IMAGE_SIZE_BUCKETS = (128, 320, 640, 1280, 1600)
_IMAGE_CACHE_TTL = 7 * 86400          # resized results are valid for a week
# An alias outlives its thumbnails: an offline client can hold a weeks-old payload.
_IMAGE_ALIAS_TTL = 30 * 86400
_IMAGE_CACHE_MAX_BYTES = 200 * 1024 * 1024
# Era originals have their own budget: the token URL that made one is dead within the hour.
_IMAGE_ORIGINALS_MAX_BYTES = 600 * 1024 * 1024
_IMAGE_ORIGINAL_MAX_BYTES = 3 * 1024 * 1024  # per original, after the 1600 px cap
_IMAGE_RESIZE_INPUT_CAP = 15 * 1024 * 1024  # don't decode >15MB
# Concurrent Pillow decodes: each can hold a 15MB input plus a 20MP decode (~80MB
# RGBA). At least 1: a Semaphore(0) would hang every resize forever.
_IMAGE_RESIZE_CONCURRENCY = max(1, int(os.environ.get("LEAKSHEET_IMAGE_RESIZE_CONCURRENCY") or 3))
_resize_sem: asyncio.Semaphore | None = None


def _resize_slot() -> asyncio.Semaphore:
    """Lazily created so the semaphore binds to the running loop."""
    global _resize_sem
    if _resize_sem is None:
        _resize_sem = asyncio.Semaphore(_IMAGE_RESIZE_CONCURRENCY)
    return _resize_sem
# Hard ceiling on what /image-proxy pulls into memory, checked while streaming.
# Above the decode cap, so a large source fails in the resize path with a clear error.
_IMAGE_DOWNLOAD_CAP = 25 * 1024 * 1024
# Compressed size says nothing about decoded size, so cap decoded pixels too,
# checked from the header before the full-frame load() below.
_IMAGE_MAX_DECODE_PIXELS = MAX_DECODE_PIXELS  # ~80MB peak as RGBA

# Only lh3-lh6 accept arbitrary =sNNN sizing; lh7-rt 403s it, so the rest take the
# Pillow path. Era covers are fetched full size at warm time (_full_size_cover_url).
_GOOGLE_RESIZABLE_HOST_RE = re.compile(r"^lh[3-6]\.googleusercontent\.com\Z", re.IGNORECASE)
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

    Returns (bytes, content_type, etag).
    """
    bin_path, meta_path = _image_cache_paths(key)
    try:
        meta = json.loads(meta_path.read_text())
        if time.time() - meta["timestamp"] > _IMAGE_CACHE_TTL:
            return None
        return bin_path.read_bytes(), meta["content_type"], meta["etag"]
    except (OSError, ValueError, KeyError):
        return None


def _write_image_cache(
    key: str, data: bytes, content_type: str, *, original: bool = False
) -> str | None:
    """Blocking write + size-cap eviction — call via asyncio.to_thread.

    Returns the entry's ETag (key plus a digest of the bytes), so the response that
    populated the cache advertises the same tag a later hit will. See
    docs/decisions.md::api.py::image-proxy-etag.
    """
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        bin_path, meta_path = _image_cache_paths(key)
        etag = f"{key}-{hashlib.sha256(data).hexdigest()[:16]}"
        meta_bytes = json.dumps({
            "content_type": content_type,
            "timestamp": time.time(),
            "etag": etag,
            **({"original": True} if original else {}),
        }).encode()
        _atomic_write_bytes(bin_path, data)
        _atomic_write_bytes(meta_path, meta_bytes)
        _maybe_evict_image_cache()
        return etag
    except OSError as e:
        logger.warning("Image cache write failed: %s", e)
        return None


_ART_SLOT_RE = re.compile(r"(leaksheet:art/v2/[0-9a-f]{32}/[0-9a-f]{32})(?:\?v=\d{1,9})?")


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


def _drop_image_thumbnails(base: str) -> None:
    """Delete every width bucket cached for *base*. Blocking."""
    for width in _IMAGE_SIZE_BUCKETS:
        for path in _image_cache_paths(_image_cache_key(base, width)):
            path.unlink(missing_ok=True)


_IMAGE_EVICT_MIN_INTERVAL = 60.0  # scan the dir at most once a minute
_last_image_evict = 0.0


def _maybe_evict_image_cache() -> None:
    """Throttle the eviction scan.

    `_evict_image_cache` stats every `img_*.bin`; running it on every write is
    thousands of stats per thumbnail on a bursty path. Same throttle as
    `_maybe_evict_sheet_cache`.
    """
    global _last_image_evict
    now = time.time()
    if now - _last_image_evict < _IMAGE_EVICT_MIN_INTERVAL:
        return
    _last_image_evict = now
    _evict_image_cache()


def _image_meta_path(bin_path: Path) -> Path:
    return bin_path.with_name(bin_path.name[:-4] + ".meta.json")


def _image_entry_kind(bin_path: Path, expired_before: float) -> tuple[bool, bool]:
    """(is an era original, has expired). Unreadable metadata counts as a live variant."""
    try:
        meta = json.loads(_image_meta_path(bin_path).read_text())
        is_original = meta.get("original") is True
        return is_original, is_original and meta["timestamp"] < expired_before
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return False, False


def _unlink_unless_rewritten(bin_path: Path, mtime: float) -> None:
    try:
        if bin_path.stat().st_mtime == mtime:  # else a worker just rewrote it
            bin_path.unlink(missing_ok=True)
            _image_meta_path(bin_path).unlink(missing_ok=True)
    except OSError:
        pass


def _trim_image_entries(entries: list[tuple[float, int, Path]], cap: int) -> None:
    """Drop the oldest entries until the rest fit *cap*."""
    entries.sort()
    total = sum(size for _, size, _ in entries)
    while entries and total > cap:
        mtime, size, victim = entries.pop(0)
        total -= size
        _unlink_unless_rewritten(victim, mtime)


def _evict_image_cache() -> None:
    """Drop oldest resized images (by mtime) once they exceed the cap, era originals
    only against their own larger budget, and cover aliases no parse has re-written in _IMAGE_ALIAS_TTL."""
    # Every warm re-writes the alias of each URL still in the sheet, and cover tokens
    # rotate, so without this sweep the directory gains a file per era per re-parse.
    alias_cutoff = time.time() - _IMAGE_ALIAS_TTL
    for alias in [*CACHE_DIR.glob("imgalias_*.txt"), *CACHE_DIR.glob("imgsrc_*.json")]:
        unlink_if_older(alias, alias_cutoff)
    variants: list = []
    originals: list = []
    expired_before = time.time() - _IMAGE_CACHE_TTL
    for bin_path in CACHE_DIR.glob("img_*.bin"):
        try:
            stat = bin_path.stat()
        except OSError:
            continue
        is_original, expired = _image_entry_kind(bin_path, expired_before)
        if expired:  # _read_image_cache would miss it; it only holds budget
            _unlink_unless_rewritten(bin_path, stat.st_mtime)
        else:
            (originals if is_original else variants).append((stat.st_mtime, stat.st_size, bin_path))
    _trim_image_entries(variants, _IMAGE_CACHE_MAX_BYTES)
    _trim_image_entries(originals, _IMAGE_ORIGINALS_MAX_BYTES)


async def _cap_original(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Downscale an era original to the widest bucket the app requests.

    Returns empty bytes when it is still over _IMAGE_ORIGINAL_MAX_BYTES (undecodable or
    too large to resize): callers then keep the cover already stored.
    """
    if not data:
        return data, content_type
    async with _resize_slot():
        data, content_type = await asyncio.to_thread(
            _resize_image_bytes, data, _IMAGE_SIZE_BUCKETS[-1], content_type
        )
    if len(data) > _IMAGE_ORIGINAL_MAX_BYTES:
        logger.info("era original not stored: %d bytes after the cap", len(data))
        return b"", ""
    return data, content_type


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
        if img.width <= w:  # header only: no full decode for an image that fits
            return data, content_type
        img.load()
    except Exception as exc:
        # Serve the original bytes, but leave a trace — a systematically
        # undecodable source would otherwise be invisible.
        logger.warning("image resize: decode failed (%s) — serving original", exc)
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


def _fits_width(data: bytes, w: int) -> bool:
    """True when *data*'s header decodes, within the pixel cap, at most *w* wide.

    Reads the header only, so it is cheap enough for the event loop.
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.width <= w and img.width * img.height <= _IMAGE_MAX_DECODE_PIXELS
    except Exception:
        return False


def _image_request_headers(url: str) -> dict[str, str]:
    # Matched on the parsed hostname, not as a substring:
    # "https://attacker.tld/?x=google.com" must not get a docs.google.com Referer.
    if _is_allowed_domain(url, set(), _GOOGLE_IMAGE_DOMAINS):
        return {"Referer": "https://docs.google.com/"}
    return {}


def _log_upstream_failure(what: str, url: str, exc: Exception) -> None:
    """Log a proxy failure: an unreachable upstream is a WARNING, anything else a bug.

    A host timing out or failing DNS is not ours to fix, and at ERROR the GlitchTip
    logging integration files it as an issue.
    """
    # NetworkError: fetcher's wrapper for an upstream non-200 or transport failure.
    # TimeoutError: a deadline of ours (asyncio.timeout) that a slow upstream hit.
    if isinstance(exc, (httpx.TransportError, NetworkError, TimeoutError)):
        logger.warning("%s: upstream unreachable for %s: %r", what, url[:80], exc)
    else:
        logger.error("%s for %s: %s", what, url[:80], exc, exc_info=exc)


def _is_sheet_image_token(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == "docs.google.com" and parsed.path.startswith("/sheets-images-rt/")


def _full_size_cover_url(url: str) -> str:
    """A sheet image at up to 1600 px: the URL a sheet emits asks for its cell's size.

    Keeps host and path, so the allowlist verdict holds.
    See docs/decisions.md::api.py::full-size-covers.
    """
    parsed = urlparse(url)
    if parsed.hostname == "docs.google.com" and parsed.path.startswith("/sheets-images-rt/"):
        return _GOOGLE_SIZE_SUFFIX_RE.sub("", url) + "=w1600"
    return url


def _pixel_count(data: bytes) -> int:
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.width * img.height
    except Exception:
        return 0


def _fingerprint(data: bytes) -> tuple[int, int | None]:
    """(pixel count, dHash) of an image: decoded once, compared many times."""
    return _pixel_count(data), _dhash(data)


def _same_fingerprint(a: tuple[int, int | None], b: tuple[int, int | None]) -> bool:
    return a[1] is not None and b[1] is not None and (a[1] ^ b[1]).bit_count() <= _SAME_ART_MAX_DISTANCE


_ERA_ART_WARM_CONCURRENCY = 3
_background_tasks: set[asyncio.Task] = set()
def _spawn_detached(coro) -> asyncio.Task:
    """Run *coro* past the request that started it, keeping a reference so
    the task is not garbage-collected mid-flight."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _warm_covers(artist) -> dict[str, str]:
    """{era name: cover URL} worth downloading. A parse carries its token URLs aside: its
    payload holds slot keys."""
    sources = artist._art_sources or {era.name: era.art_url or "" for era in artist.eras}
    covers: dict[str, str] = {}
    for name, url in sources.items():
        url = "https:" + url if url.startswith("//") else url
        if url.startswith(("http://", "https://")) and _image_host_allowed(url):
            covers[name] = url
    return covers


class _Fingerprints:
    """Per-era memo of image fingerprints, computed off the event loop."""

    def __init__(self) -> None:
        self._fps: dict[bytes, tuple[int, int | None]] = {}

    async def of(self, data: bytes) -> tuple[int, int | None]:
        if data not in self._fps:
            self._fps[data] = await asyncio.to_thread(_fingerprint, data)
        return self._fps[data]

    async def upgrades(self, current: bytes, other: bytes) -> bool:
        """True when *other* is the same picture as *current* with more pixels."""
        cur, oth = await self.of(current), await self.of(other)
        return oth[0] > cur[0] and _same_fingerprint(cur, oth)


class _EraArtWarm:
    """One tracker's cover warm: download, compare against the stored copy, keep the best."""

    def __init__(self, tracker_url: str, candidates: dict[str, str]):
        self.tracker_url = tracker_url
        self.candidates = candidates
        self.slots = asyncio.Semaphore(_ERA_ART_WARM_CONCURRENCY)

    async def _download(self, url: str) -> tuple[bytes, str]:
        async with self.slots:
            try:
                resp, data = await _get_image_capped(url, _image_request_headers(url))
                return data, resp.headers.get("content-type", "")
            except (httpx.HTTPError, httpx.InvalidURL, HTTPException, ValueError) as exc:
                logger.debug("era art warm: %s failed: %s", url[:80], exc)
                return b"", ""

    async def _download_full(self, url: str) -> tuple[bytes, str]:
        full = _full_size_cover_url(url)
        got = await self._download(full)
        got = got if got[0] or full == url else await self._download(url)
        # Capped before any comparison, so a re-warm of an unchanged picture is byte-equal.
        return await _cap_original(*got)

    async def warm(self, era_name: str, url: str) -> None:
        fps = _Fingerprints()
        # Keyed on (tracker, era), NOT the URL (see _era_art_base); the alias lets
        # /image-proxy find it under whatever token URL a client's payload holds.
        base = _era_art_base(self.tracker_url, era_name)
        key = _image_cache_key(base, None)
        await asyncio.to_thread(_write_image_alias, url, base)
        data, content_type = await self._download_full(url)
        stored = await asyncio.to_thread(_read_image_cache, key)
        data, content_type = await self._prefer_better(era_name, data, content_type, stored, fps)
        if not data:
            # Already dead (yetracker.net serves Cloudflare copies up to an hour old):
            # keep serving the era's last good cover from the slot.
            if not stored:
                return
            data, content_type = stored[0], stored[1]
        elif stored and stored[0] != data:
            await self._replace_version(base, stored[0], data, fps)
        await asyncio.to_thread(_write_image_cache, key, data, content_type, original=True)

    async def _prefer_better(self, era_name: str, data: bytes, content_type: str, stored, fps: _Fingerprints) -> tuple[bytes, str]:
        candidate = self.candidates.get(era_name)
        if data and candidate:
            better, better_type = await self._download_full(candidate)
            if better and await fps.upgrades(data, better):
                data, content_type = better, better_type
        if data and stored and await fps.upgrades(data, stored[0]):
            # A larger copy of the same picture is already stored (an Art-tab image, or
            # a full-size download that failed this time): never downgrade it.
            data, content_type = stored[0], stored[1]
        return data, content_type

    @staticmethod
    async def _replace_version(base: str, old: bytes, new: bytes, fps: _Fingerprints) -> None:
        """The sheet changed this era's cover: its thumbnails show the old one, and a new
        picture gets a new version so clients holding the old one refetch."""
        await asyncio.to_thread(_drop_image_thumbnails, base)
        # A sharper copy is a new version too, or clients keep the thumbnail they hold.
        if not _same_fingerprint(await fps.of(old), await fps.of(new)) or await fps.upgrades(old, new):
            await asyncio.to_thread(update_art_pointer, base, bump=True)


async def _warm_era_art(artist, tracker_url: str) -> None:
    """Download each era cover now, while its URL still works, and keep it.

    See docs/decisions.md::api.py::_warm_era_art. A URL that is already dead here keeps
    the era's last good cover; an Art-tab image showing the same picture replaces it
    (docs/decisions.md::fetcher.py::art-tab-identity).
    """
    covers = _warm_covers(artist)
    if not covers:
        return
    warm = _EraArtWarm(tracker_url, artist._art_candidates)
    await asyncio.gather(*(warm.warm(name, url) for name, url in covers.items()))


async def _store_slot_original(slot: str, data: bytes, ct: str) -> None:
    try:
        orig, orig_ct = await _cap_original(data, ct)
        key = _image_cache_key(slot, None)
        # A warm that finished meanwhile stored a sharper original: keep it.
        if orig and not await asyncio.to_thread(_read_image_cache, key):
            await asyncio.to_thread(_write_image_cache, key, orig, orig_ct, original=True)
    except Exception as exc:  # a failed fill only costs the next width an upstream fetch
        logger.warning("slot original not stored: %s", exc)


async def _image_source(url: str) -> tuple[str, str | None]:
    """(upstream URL, cover slot). A payload's stable cover key is served from its slot,
    filled from the slot's latest source on a miss (docs/decisions.md::api.py::_era_art_base)."""
    slot = None
    if url.startswith("leaksheet:"):
        match = _ART_SLOT_RE.fullmatch(url)
        if match is None:
            raise HTTPException(status_code=400, detail="Invalid cover key")
        slot = match.group(1)
        url = (await asyncio.to_thread(read_art_pointer, slot)).get("src", "")
    # Fix protocol-relative URLs
    if url.startswith("//"):
        url = "https:" + url
    # A slot with no recorded source can still be served from its stored copy.
    if slot is None or url:
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Invalid URL scheme")
        if not _image_host_allowed(url):
            raise HTTPException(status_code=403, detail="Domain not allowed for image proxy")
    return url, slot


def _image_base_headers() -> dict[str, str]:
    return {
        "Cache-Control": _CC_IMAGE,
        # Wider than the app CORS allowlist: web clients read covers through a canvas
        # (crossorigin="anonymous"). Reach is bounded by _image_host_allowed.
        "Access-Control-Allow-Origin": "*",
        # Served from the app's own origin: an image must never run script.
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }


async def _google_resized(url: str, width: int, headers: dict, base_headers: dict) -> Response | None:
    """Google-side resizing, preferred: no local decode, no disk cache (the CDN did the work)."""
    google_url = _rewrite_google_size(url, width)
    if google_url is None:
        return None
    try:
        # Capped, like the fallback path: a plain .get() buffers the whole body.
        resp, gdata = await _get_image_capped(google_url, headers)
    except httpx.HTTPError as exc:
        # Fall through to the original URL + Pillow path.
        logger.warning("image proxy: Google CDN resize failed for %s: %s", url[:80], exc)
        return None
    ct = resp.headers.get("content-type", "")
    if resp.status_code == 200 and _is_raster_image(ct):
        return Response(content=gdata, media_type=ct, headers={**base_headers, "X-Cache-Status": "origin"})
    return None


async def _original_image(url: str, slot: str | None, headers: dict, stored) -> tuple[bytes, str, int]:
    """(bytes, content type, upstream status) of the original: the stored copy, else the
    upstream, streamed with a byte cap (the allowlist admits drive.usercontent.google.com,
    so a plain .get() of a huge user upload could OOM the worker before any check)."""
    if stored is not None:
        return stored[0], stored[1], 200
    if not url:
        raise HTTPException(status_code=404, detail="Unknown cover")
    resp, data = await _get_image_capped(url, headers)
    ct = resp.headers.get("content-type", "")
    if slot is not None and resp.status_code == 200 and _is_raster_image(ct):
        # A cold slot keeps its original, so other widths need no upstream; the
        # capping decode runs after the response, not before it.
        _spawn_detached(_store_slot_original(slot, data, ct))
    return data, ct, resp.status_code


async def _resized_image_response(
    data: bytes, ct: str, width: int, cache_key: str, base_headers: dict
) -> Response:
    original_len = len(data)
    async with _resize_slot():
        data, ct = await asyncio.to_thread(_resize_image_bytes, data, width, ct)
    # _resize_image_bytes returns the input untouched when it refuses to decode;
    # only a resize, or an original that already fits, is filed under the width.
    status = "origin"
    if len(data) < original_len or _fits_width(data, width):
        written_etag = await asyncio.to_thread(_write_image_cache, cache_key, data, ct)
        if written_etag:
            base_headers["ETag"] = f'"{written_etag}"'
        status = "miss"
    return Response(content=data, media_type=ct, headers={**base_headers, "X-Cache-Status": status})


def _image_failure(upstream_status: int, url: str) -> HTTPException:
    # An expired Google cover token is a cover that is gone, not an outage; a 503 here
    # would also read as one.
    if upstream_status in (401, 403, 404, 410) and _is_sheet_image_token(url):
        logger.info("image proxy: expired cover token (%s) for %s", upstream_status, url[:80])
        return HTTPException(status_code=404, detail="Cover token expired")
    # Only "gone" and "slow down" relay. Anything else, a non-image 200 included,
    # is 503 (Cloudflare masks a 502).
    logger.info("image proxy: upstream %s for %s", upstream_status, url[:80])
    return HTTPException(
        status_code={404: 404, 410: 404, 429: 429}.get(upstream_status, 503),
        detail="Upstream image fetch failed",
    )


async def _serve_image(url: str, slot: str | None, width: int | None, cache_base: str, cache_key: str | None, base_headers: dict) -> Response:
    headers = _image_request_headers(url)
    # A cover _warm_era_art downloaded while its token worked. Read before any
    # upstream request, but after the thumbnail hit, which never needs the original.
    stored = await asyncio.to_thread(_read_image_cache, _image_cache_key(cache_base, None))
    if width is not None and stored is None:
        resized = await _google_resized(url, width, headers, base_headers)
        if resized is not None:
            return resized
    data, ct, upstream_status = await _original_image(url, slot, headers, stored)
    if upstream_status != 200 or not _is_raster_image(ct):
        raise _image_failure(upstream_status, url)
    if width is not None:
        return await _resized_image_response(data, ct, width, cache_key, base_headers)
    return Response(content=data, media_type=ct, headers={**base_headers, "X-Cache-Status": "origin"})


@app.get("/image-proxy", responses={
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    503: {"description": "Service Unavailable"},
})
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
    url, slot = await _image_source(url)
    width = _snap_image_width(w) if w else None
    base_headers = _image_base_headers()
    # The client's URL may be an expired cover token: resolve the (tracker, era) slot
    # it was warmed into, so original and thumbnail survive the next reparse.
    cache_base = slot or await asyncio.to_thread(_read_image_alias, url) or url

    # ETag scoped to disk cache — see docs/decisions.md::api.py::image-proxy-etag
    cache_key = None
    if width is not None:
        cache_key = _image_cache_key(cache_base, width)
        cached = await asyncio.to_thread(_read_image_cache, cache_key)
        if cached is not None:
            data, ct, entry_etag = cached
            base_headers["ETag"] = f'"{entry_etag}"'
            if _parse_if_none_match(request.headers.get("if-none-match", "")) == entry_etag:
                return Response(status_code=304, headers=base_headers)
            return Response(content=data, media_type=ct, headers={**base_headers, "X-Cache-Status": "hit"})
    try:
        return await _serve_image(url, slot, width, cache_base, cache_key, base_headers)
    except HTTPException:
        raise
    except Exception as e:
        _log_upstream_failure("Image proxy error", url, e)
        raise HTTPException(status_code=503, detail="Image proxy error") from e


def _parse_content_length(raw: str | None) -> int | None:
    """Upstream Content-Length as an int, or None when absent or unusable.

    An unreadable length only means the client gets no Content-Length. httpx joins
    repeated headers with ", ", so "123, 123" is one length; conflicting ones are not.
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

    # Re-check the allowlist on the URL we LANDED on, before reading any body; the
    # transport already refused private IPs on every hop.
    final_url = str(resp.url)
    if final_url != url and not _image_host_allowed(final_url):
        await resp.aclose()
        logger.warning("image proxy: redirect off allowlist -> %s", final_url[:120])
        raise HTTPException(status_code=503, detail="Upstream redirect not allowed")
    try:
        ct = resp.headers.get("content-type", "")
        if resp.status_code != 200 or not _is_raster_image(ct):
            return resp, b""

        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > _IMAGE_DOWNLOAD_CAP:
                raise HTTPException(status_code=503, detail="Upstream image too large")
            chunks.append(chunk)
        return resp, b"".join(chunks)
    finally:
        await resp.aclose()


# ---------------------------------------------------------------------------
# GET /api/metadata — fetch audio file metadata from provider APIs
# ---------------------------------------------------------------------------

_METADATA_USER_AGENT = USER_AGENT
# Total deadline over all of /metadata's upstream calls, not the shared client's 120 s audio
# read timeout: see docs/decisions.md::api.py::metadata-deadline.
_METADATA_DEADLINE_S = 10.0
_METADATA_TIMEOUT = httpx.Timeout(_METADATA_DEADLINE_S, connect=5.0)

# Provider metadata rarely changes for a given file, so parsed results are cached.
_metadata_cache = TTLCache(ttl=3600.0, max_entries=500)


# Known fields in pillows.su metadata — longer multi-word keys first to avoid
# partial matches (e.g. _TAG_CODEC_PROFILE before "CODEC").
_PILLOWS_FIELDS = [
    "FILE FORMAT INFO", "COMMON INFO",
    _TAG_CODEC_PROFILE, "CODEC", "CONTAINER",
    "DURATION", "BITRATE", _TAG_SAMPLE_RATE, _TAG_BITS,
    "LOSSLESS", _TAG_CHANNELS,
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


# pillows.su field → normalized key, in output order. LOSSLESS and channels convert below.
_PILLOWS_OUTPUT = (
    ("CONTAINER", "container"), ("CODEC", "codec"), (_TAG_CODEC_PROFILE, "codec_profile"),
    ("BITRATE", "bitrate"), (_TAG_SAMPLE_RATE, "sample_rate"), (_TAG_BITS, "bits_per_sample"),
    ("LOSSLESS", "lossless"), (_TAG_CHANNELS, "channels"), ("DURATION", "duration"),
    ("ARTIST", "artist"), ("TITLE", "title"),
)


def _pillows_value(key: str, val: str):
    if key == "LOSSLESS":
        return val.lower() == "true"
    if key == _TAG_CHANNELS:
        return int(val) if val.isdigit() else val
    return val


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
        val = parts[i + 1].strip()
        if val and val.lower() not in ("unknown", "null", "[object object]"):
            pairs[parts[i].strip().upper()] = val
    for key, name in _PILLOWS_OUTPUT:
        if key in pairs:
            result[name] = _pillows_value(key, pairs[key])
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
            timeout=_METADATA_TIMEOUT,
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


def _metadata_response(payload: str, status: str) -> Response:
    return Response(
        content=payload, media_type=_MIME_JSON,
        headers={"Cache-Control": _CC_METADATA, "X-Cache-Status": status},
    )


def _metadata_request_headers(provider: str, meta_url: str) -> dict[str, str]:
    headers: dict[str, str] = {"User-Agent": _METADATA_USER_AGENT}
    if provider == "pillows":
        headers["Referer"] = "https://pillows.su/"
    elif provider == "froste":
        headers["Referer"] = meta_url.rsplit("/analyze-quality", 1)[0]
    return headers


def _parse_metadata(provider: str, resp: httpx.Response, meta_url: str) -> dict:
    parsers = {
        "pillows": lambda: _parse_pillows_metadata(resp.text),
        "froste": lambda: _parse_froste_metadata(resp.json()),
        "imgur": lambda: _parse_imgur_metadata(resp.json()),
        "pixeldrain": lambda: _parse_pixeldrain_metadata(resp.json()),
    }
    try:
        parse = parsers.get(provider)
        return parse() if parse else {"provider": provider}
    # A non-JSON or oddly shaped 200 (a challenge page, a null field) is the
    # provider's outage, not a bug of ours.
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        logger.warning("Metadata from %s unreadable: %r", meta_url[:80], e)
        raise HTTPException(status_code=503, detail="Metadata fetch failed") from e


async def _fetch_metadata(url: str, meta_url: str, provider: str) -> Response:
    async with asyncio.timeout(_METADATA_DEADLINE_S):
        client = _get_shared_client()
        resp = await get_capped(client, meta_url, _metadata_request_headers(provider, meta_url), timeout=_METADATA_TIMEOUT)
        if resp.status_code == 200:
            result = _parse_metadata(provider, resp, meta_url)
        else:
            # pillows' metadata .txt endpoint 404s for some files — notably
            # videos. The CDN's Content-Type on the stream URL is accurate,
            # so fall back to a HEAD probe before giving up.
            result = await _pillows_stream_head_fallback(url) if provider == "pillows" else None
            if result is None:
                raise HTTPException(status_code=503, detail=f"Provider returned {resp.status_code}")
        payload = json.dumps(result)
        _metadata_cache.set(meta_url, payload)
        return _metadata_response(payload, "miss")


@app.get("/metadata", responses={404: {"description": "Not Found"}, 503: {"description": "Service Unavailable"}})
async def proxy_metadata(
    url: str = Query(..., description="Original file-sharing link"),
):
    """Fetch audio file metadata from provider APIs."""
    meta_info = resolve_metadata_url(url)
    if not meta_info:
        raise HTTPException(status_code=404, detail="No metadata API for this provider")
    meta_url = meta_info["url"]
    cached = _metadata_cache.get(meta_url)
    if cached is not None:
        return _metadata_response(cached, "hit")
    try:
        return await _fetch_metadata(url, meta_url, meta_info["provider"])
    except HTTPException:
        raise
    except Exception as e:
        _log_upstream_failure("Metadata proxy error", meta_url, e)
        raise HTTPException(status_code=503, detail="Metadata fetch failed") from e


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

    Deliberately does no I/O: it answers "the event loop can serve a request",
    which is exactly what the watchdog needs to know.
    """
    return Response(
        # Compact: uptime monitors match the keyword "status":"ok" in this body.
        content=json.dumps({"status": "ok", "version": VERSION}, separators=(",", ":")),
        media_type=_MIME_JSON,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/trackers")
async def list_trackers():
    """List artist trackers from the ArtistGrid registry CSV (cached 1h).

    Falls back to the last successful fetch, or if there's none yet, to the
    built-in seed list (src/tracker_seed.py) — see X-Cache-Status.
    """
    global _trackers_fail_until

    # Back off after a failure: this endpoint is outside the rate limiter, so retrying
    # per request would amplify an ArtistGrid outage against a third party.
    if time.monotonic() < _trackers_fail_until:
        return _trackers_fallback_response()

    cached = _trackers_cache.get("trackers")
    if cached is not None:
        return Response(
            content=cached,
            media_type=_MIME_JSON,
            headers={
                "Cache-Control": _CC_METADATA,
                "X-Cache-Status": "hit",
            },
        )

    try:
        payload = await _load_trackers_once()
        return Response(
            content=payload,
            media_type=_MIME_JSON,
            headers={
                "Cache-Control": _CC_METADATA,
                "X-Cache-Status": "miss",
            },
        )
    except Exception:
        _trackers_fail_until = time.monotonic() + _TRACKERS_FAIL_BACKOFF_S
        return _trackers_fallback_response()


# Coalesces simultaneous cold fetches of the registry, per worker.
_trackers_inflight: asyncio.Task[str] | None = None


async def _load_trackers_once() -> str:
    global _trackers_inflight
    if _trackers_inflight is None or _trackers_inflight.done():
        _trackers_inflight = asyncio.create_task(_fetch_trackers_payload())
    return await asyncio.shield(_trackers_inflight)


async def _fetch_trackers_payload() -> str:
    global _trackers_stale
    try:
        # Also registers every listed tracker's host — this is the warm path
        # for the /sheet allowlist (see config.sheet_host_allowed).
        entries = await fetch_artistgrid_entries()
    except Exception as e:
        _log_upstream_failure("ArtistGrid fetch failed", ARTISTGRID_URL, e)
        raise
    payload = json.dumps([e.model_dump() for e in entries])
    _trackers_cache.set("trackers", payload)
    _trackers_stale = payload
    return payload


def _trackers_fallback_response() -> Response:
    """Last good fetch if we have one, else the built-in seed list."""
    if _trackers_stale is not None:
        return Response(
            content=_trackers_stale,
            media_type=_MIME_JSON,
            headers={
                "Cache-Control": _CC_TRACKERS_STALE,
                "X-Cache-Status": "stale",
            },
        )
    return Response(
        content=_SEED_PAYLOAD,
        media_type=_MIME_JSON,
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


# Digit runs are BOUNDED: Python caps str->int at 4300 digits, and these int() calls
# sit outside /stream's try block. 19 digits covers any int64 offset.
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
        if n == 0 or total_size == 0:
            return _RangePlan("unsatisfiable")  # names no bytes, or the file has none
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
            # Unknown total: a synthesised 206 needs a Content-Range end. Serve 200 from byte 0
            # (docs/decisions.md::api.py::range-fallback).
            return _RangePlan("full")
        return _RangePlan("partial", start, total_size - 1)

    end = int(last)
    if end < start:
        return _RangePlan("full")  # malformed → ignore the header
    if total_size is None:
        # Unknown total: we can't clamp, so can't promise a Content-Length. Serve the full
        # body rather than a 206 advertising the requested length.
        return _RangePlan("full")
    end = min(end, total_size - 1)
    return _RangePlan("partial", start, end)


async def _slice_byte_stream(source, range_start: int, range_end: int):
    """Yield only bytes [range_start, range_end] (inclusive) from a chunked stream.

    Used to synthesise HTTP 206 responses when the upstream host ignores
    Range requests. Stops consuming the source once the range is served.
    Everything before `range_start` is downloaded and discarded.
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
        if chunk_end <= range_start:
            skipped += len(chunk)
            continue
        start_in_chunk = max(0, range_start - skipped)
        end_in_chunk = min(len(chunk), range_end + 1 - skipped)
        portion = chunk[start_in_chunk:end_in_chunk]
        if portion:
            yield portion
        skipped += len(chunk)
        if skipped > range_end:
            break


async def _record_stream_outcome(provider: str | None, link: str, exc: Exception | None) -> None:
    """Feed one /stream upstream outcome into the shared provider health."""
    if provider is None:
        return
    if exc is None or isinstance(exc, NonMediaError) or (
        isinstance(exc, UpstreamStatusError) and exc.status_code < 500
    ):
        await asyncio.to_thread(host_health.record_success, provider)  # the host answered
        return
    if isinstance(exc, httpx.PoolTimeout):
        return  # our own pool is saturated: the host was never asked
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        hard = True  # no connection at all: the host itself is unreachable
    elif isinstance(exc, (httpx.TransportError, ValueError)):
        hard = False
    else:
        return  # a bug of ours says nothing about the host
    await asyncio.to_thread(
        host_health.record_failure, provider, link, hard=hard, error=type(exc).__name__
    )


@app.get("/hosts")
async def list_stream_hosts() -> Response:
    """Health of each streaming provider, from real /stream traffic and recovery probes."""
    hosts = await asyncio.to_thread(host_health.snapshot)
    return Response(
        content=json.dumps({"hosts": hosts}),
        media_type=_MIME_JSON,
        headers={"Cache-Control": "public, max-age=30"},
    )


async def _stream_target(url: str) -> tuple[str, str | None]:
    """The resolved stream URL and its provider; refuses unsupported, disallowed or down hosts."""
    stream_url = resolve_stream_url(url)
    if stream_url is None:
        raise HTTPException(status_code=400, detail="URL is not from a supported streaming host")
    if not _is_allowed_domain(stream_url, ALLOWED_STREAM_HOSTS):
        raise HTTPException(status_code=403, detail="Domain not allowed for audio streaming")
    # A provider known to be down is refused at once, until a retry is due: see
    # docs/decisions.md::host_health.py.
    provider = host_health.provider_of(stream_url)
    if provider and (outage := await asyncio.to_thread(host_health.refusing, provider)):
        raise HTTPException(
            status_code=503,
            detail=f"{outage['host']} is temporarily unavailable",
            headers={"Retry-After": "60"},
        )
    return stream_url, provider


def _client_range(range_header: str | None) -> tuple[str | None, int, bool]:
    """(Range header to forward, its start byte, whether it is a suffix range).

    Malformed or multi-part Range headers are ignored per RFC 7233 (serve 200 full),
    not forwarded: upstreams turn garbage Range values into hard errors."""
    spec = _RANGE_SPEC.match(range_header.strip()) if range_header else None
    if range_header and (not spec or (spec[1] and spec[2] and int(spec[2]) < int(spec[1]))):
        return None, 0, False  # malformed or inverted: ignored, never forwarded
    if not range_header:
        return None, 0, False
    start = re.match(r"bytes=(\d{1,19})-", range_header)
    if start:
        return range_header, int(start.group(1)), False
    return range_header, 0, bool(re.match(r"bytes=-\d+", range_header))


def _upstream_status_exception(e: UpstreamStatusError) -> HTTPException:
    """Relay upstream's 4xx so a client can tell "gone" from "throttled"; only the code
    crosses over (see UpstreamStatusError). Everything else is 503."""
    if e.status_code in (404, 410):
        return HTTPException(status_code=404, detail="Upstream file not found")
    if e.status_code == 429:
        return HTTPException(status_code=429, detail="Upstream rate limited", headers={"Retry-After": "30"})
    if e.status_code in (401, 403):
        # Not 403: that is our own "Domain not allowed", and a client must tell them apart.
        return HTTPException(status_code=424, detail="upstream_forbidden")
    if 400 <= e.status_code < 500:
        return HTTPException(status_code=e.status_code, detail="Upstream refused the request")
    return HTTPException(status_code=503, detail=_UPSTREAM_ERROR)


async def _open_stream(url: str, stream_url: str, provider: str | None, range_header: str | None) -> httpx.Response:
    """The upstream response, with every failure mapped to the status a client acts on."""
    try:
        resp = await stream_audio(stream_url, range_header=range_header)
    except GdriveInterstitialError as e:
        # Never proxy HTML as audio — see docs/decisions.md::api.py::gdrive-interstitial
        logger.warning("gdrive interstitial for %s: %s", stream_url, e)
        await _record_stream_outcome(provider, url, None)  # drive answered; the file needs a confirm
        raise HTTPException(status_code=409, detail="gdrive_interstitial") from e
    except UpstreamStatusError as e:
        logger.warning("Stream upstream %s for %s", e.status_code, stream_url)
        await _record_stream_outcome(provider, url, e)
        raise _upstream_status_exception(e) from e
    except NonMediaError as e:
        logger.warning("Stream non-media for %s: %s", stream_url, e)
        await _record_stream_outcome(provider, url, e)
        raise HTTPException(status_code=415, detail="not_media") from e
    except ValueError as e:
        # The message can name internal hosts and SSRF-check internals: log it, return
        # something generic.
        logger.warning("Stream error for %s: %s", stream_url, e)
        await _record_stream_outcome(provider, url, e)
        raise HTTPException(status_code=503, detail=_UPSTREAM_ERROR) from e
    except Exception as e:
        _log_upstream_failure("Stream error", stream_url, e)
        await _record_stream_outcome(provider, url, e)
        raise HTTPException(status_code=503, detail=_UPSTREAM_ERROR) from e
    await _record_stream_outcome(provider, url, None)
    return resp


async def _refusal_response(resp: httpx.Response) -> Response | None:
    """A 403 or 416 the upstream returned (not raised), closed and relayed."""
    # Permission-required/private gdrive files come back from stream_audio
    # as a real 403 response object (not raised); see the 424 mapping above.
    if resp.status_code == 403:
        await resp.aclose()
        raise HTTPException(status_code=424, detail="upstream_forbidden")
    # Upstream judged the (valid) range unsatisfiable — relay it faithfully
    # instead of collapsing it into a generic 503.
    if resp.status_code == 416:
        cr = resp.headers.get("content-range")
        await resp.aclose()
        return Response(status_code=416, headers={"Content-Range": cr or "bytes */*"})
    return None


class _UpstreamBody:
    """The upstream body with its sniffed first chunk put back in front; every stream
    it hands out closes the upstream response when done."""

    def __init__(self, resp: httpx.Response):
        self.resp = resp
        self.iterator = resp.aiter_bytes()
        self.prepend = b""

    async def sniff(self, url: str) -> bytes:
        """Read the first _SNIFF_BYTES for MIME sniffing — see docs/decisions.md::api.py::mime-sniffing"""
        try:
            while len(self.prepend) < _SNIFF_BYTES:
                self.prepend += await self.iterator.__anext__()
        except StopAsyncIteration:
            pass
        except Exception as exc:
            # A read error while sniffing would leak `resp`'s pooled connection: close it and
            # surface a 503.
            await self.resp.aclose()
            logger.warning("stream first-chunk read failed for %s: %s", url[:80], exc)
            raise HTTPException(status_code=503, detail="Upstream read error") from exc
        return self.prepend

    async def _chunks(self):
        if self.prepend:
            yield self.prepend
        async for chunk in self.iterator:
            yield chunk

    async def _closing(self, iterator):
        try:
            async for chunk in iterator:
                yield chunk
        finally:
            await self.resp.aclose()

    def stream(self):
        return self._closing(self._chunks())

    def slice(self, start: int, end: int):
        # The slice operates on the FULL byte-offset stream (prepend chunk first).
        return self._closing(_slice_byte_stream(self._chunks(), start, end))


def _passthrough_206_headers(resp: httpx.Response, ct: str | None, disposition: str | None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept-Ranges": "bytes"}
    if disposition:
        headers["Content-Disposition"] = disposition
    if ct:
        headers["Content-Type"] = ct
    cr = resp.headers.get("content-range")
    if cr:
        headers["Content-Range"] = cr
        # Derive Content-Length from Content-Range: some upstreams (pillows.su) send the
        # total size even on a 206, which breaks iOS Safari. Bounded digits, as _RANGE_SPEC.
        cr_match = re.match(r"bytes (\d{1,18})-(\d{1,18})/", cr)
        if cr_match and int(cr_match.group(2)) >= int(cr_match.group(1)):
            headers["Content-Length"] = str(int(cr_match.group(2)) - int(cr_match.group(1)) + 1)
    if "Content-Length" not in headers:
        cl = _parse_content_length(resp.headers.get("content-length"))
        if cl is not None:
            headers["Content-Length"] = str(cl)
    return headers


def _full_body_headers(ct: str | None, disposition: str | None, total_size: int | None) -> dict[str, str]:
    headers = {"Accept-Ranges": "bytes"}
    if disposition:
        headers["Content-Disposition"] = disposition
    if ct:
        headers["Content-Type"] = ct
    if total_size is not None:
        headers["Content-Length"] = str(total_size)
    return headers


async def _synthesized_range_response(
    body: _UpstreamBody, range_header: str, total_size: int | None, ct: str | None, disposition: str | None,
) -> Response:
    """Client requested Range but upstream ignored it — plan the response."""
    plan = _plan_synthesized_range(range_header, total_size)
    if plan.kind == "unsatisfiable":
        await body.resp.aclose()
        cr_total = str(total_size) if total_size is not None else "*"
        return Response(status_code=416, headers={"Content-Range": f"bytes */{cr_total}"})
    headers = {"Accept-Ranges": "bytes", "Content-Type": ct or _MIME_OCTET}
    if plan.kind == "full":
        # 200-not-206 fallback — see docs/decisions.md::api.py::range-fallback
        if disposition:
            headers["Content-Disposition"] = disposition
        return StreamingResponse(body.stream(), status_code=200, headers=headers, media_type=ct or _MIME_OCTET)
    # Synthesise a 206 with Content-Range ('*' total is valid per RFC 7233 when the complete
    # length is unknown). A 'partial' plan is only made when total_size is known.
    headers["Content-Length"] = str(plan.end - plan.start + 1)
    headers["Content-Range"] = f"bytes {plan.start}-{plan.end}/{total_size}"
    if disposition:
        headers["Content-Disposition"] = disposition
    return StreamingResponse(
        body.slice(plan.start, plan.end), status_code=206, headers=headers, media_type=ct or _MIME_OCTET,
    )


@app.get("/stream", responses={
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    415: {"description": "Unsupported Media Type"},
    424: {"description": "Failed Dependency"},
    429: {"description": "Too Many Requests"},
    503: {"description": "Service Unavailable"},
})
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
    stream_url, provider = await _stream_target(url)
    # The range shape is parsed early: the MIME sniffing decision below needs it.
    range_header, range_start, is_suffix_range = _client_range(request.headers.get("range"))
    resp = await _open_stream(url, stream_url, provider, range_header)
    refusal = await _refusal_response(resp)
    if refusal is not None:
        return refusal

    ct = _fix_audio_mime(
        resp.headers.get("content-type"), url=str(resp.url), content_disposition=resp.headers.get("content-disposition")
    )
    total_size = _parse_content_length(resp.headers.get("content-length"))
    body = _UpstreamBody(resp)
    # The first body byte is file byte 0 on a 200, or on a 206 whose range starts at 0.
    # A 206 to a suffix range ('bytes=-N') starts at the file TAIL: never sniff it.
    if resp.status_code == 200 or (range_start == 0 and not is_suffix_range):
        head = await body.sniff(url)
        sniffed = _sniff_audio_format(head[:_SNIFF_BYTES])
        if sniffed:
            ct = sniffed
        elif _is_non_media(head):
            await resp.aclose()
            raise HTTPException(status_code=415, detail="Not an audio or video file")

    # When ?download=true, add Content-Disposition with correct extension
    disposition = f'attachment; filename="track{_MIME_TO_EXT.get(ct, ".mp3")}"' if download else None
    # Upstream DID handle Range: pass through as-is.
    if resp.status_code == 206:
        headers = _passthrough_206_headers(resp, ct, disposition)
        return StreamingResponse(body.stream(), status_code=206, headers=headers, media_type=ct or _MIME_OCTET)
    # Upstream returned 200 (no Range support) and the client didn't ask for Range either.
    if not range_header:
        headers = _full_body_headers(ct, disposition, total_size)
        return StreamingResponse(body.stream(), status_code=200, headers=headers, media_type=ct or _MIME_OCTET)
    return await _synthesized_range_response(body, range_header, total_size, ct, disposition)
