"""LeakSheet — FastAPI HTTP layer.

Endpoints:
  POST /sheet       — send a tracker URL, get parsed Artist JSON back
  GET  /image-proxy — proxy images through backend (CORS bypass)
  GET  /stream      — proxy audio from supported file hosts (CORS bypass)
  POST /cache/clear — clear the URL fetch cache

Note: In production (DO App Platform), these are served under /api/* via
ingress routing.  The /api prefix is stripped by the platform before reaching
this app.  In local dev, Vite's proxy rewrites /api/* → /* when forwarding.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager

import httpx

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import StreamingResponse

from src.fetcher import (
    AccessDeniedError,
    async_fetch_and_parse,
    clear_cache,
    InvalidURLError,
    NetworkError,
    NoTablesError,
    ParseError,
)
from src.streaming import (
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
    # Partial Ogg (only 1-2 bytes received, e.g. from bytes=0-1 Safari probe)
    if len(header) >= 1 and header[0:1] == b"O" and (len(header) < 4):
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
    _MP4_BOXES = {b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot"}
    if len(header) >= 8 and header[4:8] in _MP4_BOXES:
        return "audio/mp4"

    return None

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

_STREAM_ALLOWED_DOMAINS = {
    # Exact hostnames allowed for stream proxy
    "pillows.su",
    "pillowcase.su",
    "api.pillows.su",
    "imgur.gg",
    "temp.imgur.gg",
    "music.froste.lol",
    "krakenfiles.com",
    "cdn.krakenfiles.com",
}


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
            headers={
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

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").rstrip("/") == "/stream":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No explicit startup work needed — _proxy_client is lazily initialised on
    # first use by _get_proxy_client().
    yield
    # Shutdown: close both shared HTTP clients to release connections cleanly.
    if _proxy_client is not None:
        await _proxy_client.aclose()
    await close_shared_client()


app = FastAPI(
    title="LeakSheet",
    description="Parser + API for Google Spreadsheet-based music tracker documents",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(_StreamSafeGZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition"],
)


# ---------------------------------------------------------------------------
# POST /api/sheet — parse a tracker URL → full Artist JSON
# ---------------------------------------------------------------------------

class SheetRequest(BaseModel):
    url: str = Field(..., description="Tracker URL (Google Sheets htmlview or custom domain)")
    artist_name: str | None = Field(None, description="Override inferred artist name")
    use_cache: bool = Field(True, description="Whether to use cached data")
    force_refresh: bool = Field(False, description="Force a fresh fetch, ignoring cache")


@app.post("/sheet")
async def parse_sheet(req: SheetRequest):
    """Fetch and parse a tracker spreadsheet.

    Accepts a Google Sheets /htmlview URL or a custom tracker domain.
    Returns the full parsed Artist object with all eras, songs, and versions.
    """
    cache_ttl = 0 if req.force_refresh else 3600
    use_cache = req.use_cache and not req.force_refresh

    try:
        artist = await async_fetch_and_parse(
            req.url,
            artist_name=req.artist_name,
            cache_ttl=cache_ttl,
            use_cache=use_cache,
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

    data = artist.model_dump()
    return data


# ---------------------------------------------------------------------------
# POST /api/cache/clear — clear the fetch cache
# ---------------------------------------------------------------------------

@app.post("/cache/clear")
async def clear_fetch_cache():
    """Clear the URL fetch cache."""
    count = clear_cache()
    return {"cleared": count}


# ---------------------------------------------------------------------------
# GET /api/image-proxy — proxy images with CORS headers
# ---------------------------------------------------------------------------

@app.get("/image-proxy")
async def proxy_image(url: str = Query(..., description="Image URL to proxy")):
    """Proxy an image through the backend to avoid CORS issues.

    Used by the frontend to load era cover art images from Google CDN
    which don't serve Access-Control-Allow-Origin headers.
    """
    # Fix protocol-relative URLs
    if url.startswith("//"):
        url = "https:" + url

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")

    if not _is_allowed_domain(url, _IMAGE_ALLOWED_DOMAINS, _IMAGE_ALLOWED_PARENT_DOMAINS):
        raise HTTPException(status_code=403, detail="Domain not allowed for image proxy")

    # Conditional headers — send browser-like headers for Google domains
    is_google = any(h in url for h in (
        'googleusercontent.com', 'ggpht.com', 'google.com', 'gstatic.com',
    ))
    headers = {}
    if is_google:
        headers["Referer"] = "https://docs.google.com/"

    try:
        resp = await _get_proxy_client().get(url, headers=headers)
        ct = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ct.startswith("image/"):
            return Response(
                content=resp.content,
                media_type=ct,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Access-Control-Allow-Origin": "*",
                },
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

_METADATA_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LeakSheet/1.0"


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
    return result


def _parse_froste_metadata(data: dict) -> dict:
    """Normalize froste.lol analyze-quality JSON."""
    result: dict = {"provider": "froste"}
    if "estimatedBitrate" in data:
        result["estimated_bitrate"] = data["estimatedBitrate"]
        result["bitrate"] = f"{data['estimatedBitrate']}kbps"
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
    return result


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

    headers: dict[str, str] = {"User-Agent": _METADATA_USER_AGENT}
    if provider == "pillows":
        headers["Referer"] = "https://pillows.su/"
    elif provider == "froste":
        headers["Referer"] = meta_url.rsplit("/analyze-quality", 1)[0]

    try:
        client = _get_shared_client()
        resp = await client.get(meta_url, headers=headers)
        if resp.status_code != 200:
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
        else:
            result = {"provider": provider}

        return Response(
            content=json.dumps(result),
            media_type="application/json",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Metadata proxy error: %s", e)
        raise HTTPException(status_code=502, detail="Metadata fetch failed")


# ---------------------------------------------------------------------------
# GET /api/stream — proxy audio (CORS bypass) with range request support
# ---------------------------------------------------------------------------

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

    # Forward Range header from client if present
    range_header = request.headers.get("range")

    # Parse range_start early — needed for MIME sniffing decision below.
    _range_start = 0
    if range_header:
        _rs_m = re.match(r"bytes=(\d+)-", range_header)
        if _rs_m:
            _range_start = int(_rs_m.group(1))

    try:
        resp = await stream_audio(stream_url, range_header=range_header)
    except ValueError as e:
        logger.warning("Stream error for %s: %s", stream_url, e)
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("Stream error for %s: %s", stream_url, e)
        raise HTTPException(status_code=502, detail="Upstream error")

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

    if _range_start == 0:
        try:
            _prepend_chunk = await _stream_iter.__anext__()
        except StopAsyncIteration:
            _prepend_chunk = b""
        sniffed = _sniff_audio_format(_prepend_chunk[:16] if _prepend_chunk else b"")
        if sniffed:
            ct = sniffed

    # When ?download=true, add Content-Disposition with correct extension
    if download:
        ext = _MIME_TO_EXT.get(ct, ".mp3")
        _disposition = f'attachment; filename="track{ext}"'
    else:
        _disposition = None

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

        async def _iter_passthrough():
            try:
                if _prepend_chunk:
                    yield _prepend_chunk
                async for chunk in _stream_iter:
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(
            _iter_passthrough(),
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

        async def _iter_full():
            try:
                if _prepend_chunk:
                    yield _prepend_chunk
                async for chunk in _stream_iter:
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(
            _iter_full(),
            status_code=200,
            headers=headers,
            media_type=ct or "application/octet-stream",
        )

    # Client requested Range but upstream ignored it — synthesise 206.
    m = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        await resp.aclose()
        raise HTTPException(status_code=416, detail="Malformed Range header")

    range_start = int(m.group(1))
    range_end = int(m.group(2)) if m.group(2) else (total_size - 1 if total_size else None)

    if total_size and range_start >= total_size:
        await resp.aclose()
        raise HTTPException(status_code=416, detail="Range start beyond file size")

    # Build a unified source iterator (prepend chunk + rest of stream).
    # The slice logic below must operate on the FULL byte-offset stream,
    # so we iterate through _prepend_chunk first then _stream_iter.
    async def _source_iter():
        if _prepend_chunk:
            yield _prepend_chunk
        async for chunk in _stream_iter:
            yield chunk

    if range_end is None:
        # Unknown total size — cannot synthesise a valid 206 without knowing the
        # Content-Range end byte. Return the full stream from byte 0 as HTTP 200,
        # which correctly signals to the browser that Range is not supported for
        # this response. iOS Safari interprets HTTP 200 to a Range request as
        # "full file from byte 0"; returning partial data starting at range_start
        # here would corrupt its byte-offset-to-timestamp mapping.
        async def _iter_full_unknown():
            try:
                async for chunk in _source_iter():
                    yield chunk
            finally:
                await resp.aclose()

        _unknown_headers: dict[str, str] = {
            "Accept-Ranges": "bytes",
            "Content-Type": ct or "application/octet-stream",
        }
        if _disposition:
            _unknown_headers["Content-Disposition"] = _disposition

        return StreamingResponse(
            _iter_full_unknown(),
            status_code=200,
            headers=_unknown_headers,
            media_type=ct or "application/octet-stream",
        )

    # Known total — return proper 206 with Content-Range
    content_length = range_end - range_start + 1

    async def _iter_range():
        try:
            skipped = 0
            sent = 0
            async for chunk in _source_iter():
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
                    sent += len(portion)
                skipped += len(chunk)
                # Past range_end — stop
                if skipped > range_end:
                    break
        finally:
            await resp.aclose()

    return StreamingResponse(
        _iter_range(),
        status_code=206,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Type": ct or "application/octet-stream",
            "Content-Length": str(content_length),
            "Content-Range": f"bytes {range_start}-{range_end}/{total_size}",
        },
        media_type=ct or "application/octet-stream",
    )
