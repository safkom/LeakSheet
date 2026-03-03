"""LeakSheet — FastAPI HTTP layer.

Endpoints:
  POST /api/sheet       — send a tracker URL, get parsed Artist JSON back
  GET  /api/image-proxy — proxy images through backend (CORS bypass)
  GET  /api/stream      — proxy audio from supported file hosts (CORS bypass)
  POST /api/cache/clear — clear the URL fetch cache
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager

import httpx

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from src.fetcher import (
    async_fetch_and_parse,
    clear_cache,
    InvalidURLError,
    NetworkError,
    NoTablesError,
    ParseError,
)
from src.streaming import resolve_stream_url, stream_audio


# ---------------------------------------------------------------------------
# SSRF protection — domain allowlists for proxy endpoints
# ---------------------------------------------------------------------------

_IMAGE_ALLOWED_DOMAINS = {
    "googleusercontent.com",
    "ggpht.com",
    "google.com",
    "gstatic.com",
    "lh3.googleusercontent.com",
    "lh7-rt.googleusercontent.com",
}

_STREAM_ALLOWED_DOMAINS = {
    "pillows.su",
    "pillowcase.su",
    "api.pillows.su",
    "imgur.gg",
    "temp.imgur.gg",
    "music.froste.lol",
}


def _is_allowed_domain(url: str, allowed: set[str]) -> bool:
    """Check if the URL's hostname matches any of the allowed domains.

    Handles both exact matches (e.g. "api.pillows.su") and suffix matches
    (e.g. "lh3.googleusercontent.com" matches "googleusercontent.com").
    """
    from urllib.parse import urlparse
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        return any(hostname == d or hostname.endswith("." + d) for d in allowed)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

# Global HTTP client for proxies to reuse connection pools
proxy_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global proxy_client
    proxy_client = httpx.AsyncClient(
        timeout=15,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    yield
    await proxy_client.aclose()


app = FastAPI(
    title="LeakSheet",
    description="Parser + API for Google Spreadsheet-based music tracker documents",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# ---------------------------------------------------------------------------
# POST /api/sheet — parse a tracker URL → full Artist JSON
# ---------------------------------------------------------------------------

class SheetRequest(BaseModel):
    url: str = Field(..., description="Tracker URL (Google Sheets htmlview or custom domain)")
    artist_name: str | None = Field(None, description="Override inferred artist name")
    use_cache: bool = Field(True, description="Whether to use cached data")
    force_refresh: bool = Field(False, description="Force a fresh fetch, ignoring cache")


@app.post("/api/sheet")
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
    except NetworkError as e:
        raise HTTPException(status_code=502, detail=f"Network error: {e}")
    except NoTablesError as e:
        raise HTTPException(status_code=404, detail=f"No table data found: {e}")
    except ParseError as e:
        raise HTTPException(status_code=422, detail=f"Parse error: {e}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")

    data = artist.dict()
    return data


# ---------------------------------------------------------------------------
# POST /api/cache/clear — clear the fetch cache
# ---------------------------------------------------------------------------

@app.post("/api/cache/clear")
async def clear_fetch_cache():
    """Clear the URL fetch cache."""
    count = clear_cache()
    return {"cleared": count}


# ---------------------------------------------------------------------------
# GET /api/image-proxy — proxy images with CORS headers
# ---------------------------------------------------------------------------

@app.get("/api/image-proxy")
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

    if not _is_allowed_domain(url, _IMAGE_ALLOWED_DOMAINS):
        raise HTTPException(status_code=403, detail="Domain not allowed for image proxy")

    # Conditional headers — send browser-like headers for Google domains
    is_google = any(h in url for h in (
        'googleusercontent.com', 'ggpht.com', 'google.com', 'gstatic.com',
    ))
    headers = {}
    if is_google:
        headers["Referer"] = "https://docs.google.com/"

    try:
        resp = await proxy_client.get(url, headers=headers)
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
        raise HTTPException(status_code=502, detail=f"Image proxy error: {e}")


# ---------------------------------------------------------------------------
# GET /api/stream — proxy audio (CORS bypass) with range request support
# ---------------------------------------------------------------------------

@app.get("/api/stream")
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

    try:
        resp, client = await stream_audio(stream_url, range_header=range_header)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    ct = resp.headers.get("content-type")
    total_size = int(resp.headers["content-length"]) if "content-length" in resp.headers else None

    # When ?download=true, add Content-Disposition to force browser download
    _disposition = 'attachment; filename="track.mp3"' if download else None

    # ---------- upstream DID handle Range → pass through as-is ----------
    if resp.status_code == 206:
        headers: dict[str, str] = {"Accept-Ranges": "bytes"}
        if _disposition:
            headers["Content-Disposition"] = _disposition
        if ct:
            headers["Content-Type"] = ct
        cl = resp.headers.get("content-length")
        if cl:
            headers["Content-Length"] = cl
        cr = resp.headers.get("content-range")
        if cr:
            headers["Content-Range"] = cr

        async def _iter_passthrough():
            try:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

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
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            _iter_full(),
            status_code=200,
            headers=headers,
            media_type=ct or "application/octet-stream",
        )

    # Client requested Range but upstream ignored it — synthesise 206.
    m = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        await resp.aclose(); await client.aclose()
        raise HTTPException(status_code=416, detail="Malformed Range header")

    range_start = int(m.group(1))
    range_end = int(m.group(2)) if m.group(2) else (total_size - 1 if total_size else None)

    if total_size and range_start >= total_size:
        await resp.aclose(); await client.aclose()
        raise HTTPException(status_code=416, detail="Range start beyond file size")

    if range_end is None:
        # Unknown total — stream from offset, skip leading bytes
        async def _iter_skip():
            try:
                skipped = 0
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    if skipped + len(chunk) <= range_start:
                        skipped += len(chunk)
                        continue
                    if skipped < range_start:
                        offset = range_start - skipped
                        yield chunk[offset:]
                        skipped += len(chunk)
                    else:
                        yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            _iter_skip(),
            status_code=200,
            headers={"Accept-Ranges": "bytes", "Content-Type": ct or "application/octet-stream"},
            media_type=ct or "application/octet-stream",
        )

    # Known total — return proper 206 with Content-Range
    content_length = range_end - range_start + 1

    async def _iter_range():
        try:
            skipped = 0
            sent = 0
            async for chunk in resp.aiter_bytes(chunk_size=65536):
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
            await client.aclose()

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
