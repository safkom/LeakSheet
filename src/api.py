"""LeakSheet — FastAPI HTTP layer.

Serves parsed tracker data from an in-memory store.
On startup, fetches and parses all URLs from Trackers/links.txt.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from starlette.responses import StreamingResponse

from src.config import TRACKERS_DIR
from src.fetcher import fetch_and_parse, fetch_links_file, clear_cache
from src.models import Artist, Era, Song, SongVersion, Section, ParseMetadata, TimelineEvent
from src.streaming import resolve_stream_url, find_streamable_link, is_streamable, stream_audio


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_store: dict[str, Artist] = {}


def _load_trackers() -> None:
    """Parse all URLs from links.txt into the in-memory store."""
    links_path = TRACKERS_DIR / "links.txt"
    artists = fetch_links_file(links_path)
    for artist in artists:
        _store[artist.slug] = artist


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load trackers from links.txt into memory."""
    _load_trackers()
    yield


app = FastAPI(
    title="LeakSheet",
    description="Parser + API for Google Spreadsheet-based music tracker documents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Response models (thin wrappers — avoid exposing full internal models)
# ---------------------------------------------------------------------------

class ArtistSummary(BaseModel):
    name: str
    slug: str
    source_url: str | None = None
    era_count: int
    total_songs: int
    total_versions: int


class EraSummary(BaseModel):
    name: str
    description: str | None = None
    timeline: list[TimelineEvent] = []
    art_url: str | None = None
    highlighted_producers: list[str] = []
    song_count: int
    version_count: int
    stats_raw: str | None = None


class SongDetail(BaseModel):
    base_name: str
    era_name: str
    versions: list[SongVersion]


class SearchResult(BaseModel):
    artist_name: str
    artist_slug: str
    era_name: str
    song: Song


class ParseRequest(BaseModel):
    url: str = Field(..., description="Tracker URL to parse")
    artist_name: str | None = Field(None, description="Override artist name")


class ParseResponse(BaseModel):
    name: str
    slug: str
    era_count: int
    total_songs: int
    parse_metadata: ParseMetadata | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/artists", response_model=list[ArtistSummary])
def list_artists():
    """List all loaded artists."""
    return [
        ArtistSummary(
            name=a.name,
            slug=a.slug,
            source_url=a.source_url,
            era_count=len(a.eras),
            total_songs=a.total_songs,
            total_versions=a.total_versions,
        )
        for a in _store.values()
    ]


def _era_to_summary(e: Era) -> EraSummary:
    """Convert an Era model to an EraSummary response."""
    return EraSummary(
        name=e.name,
        description=e.description,
        timeline=e.timeline,
        art_url=e.art_url,
        highlighted_producers=e.highlighted_producers,
        song_count=e.song_count,
        version_count=e.version_count,
        stats_raw=e.stats_raw,
    )


@app.get("/api/artists/{slug}")
def get_artist(slug: str):
    """Artist detail with era list."""
    artist = _store.get(slug)
    if not artist:
        raise HTTPException(status_code=404, detail=f"Artist '{slug}' not found")
    return {
        "name": artist.name,
        "slug": artist.slug,
        "source_url": artist.source_url,
        "total_songs": artist.total_songs,
        "total_versions": artist.total_versions,
        "parse_metadata": artist.parse_metadata,
        "tracker_stats": artist.tracker_stats,
        "eras": [_era_to_summary(e) for e in artist.eras],
    }


@app.get("/api/artists/{slug}/eras", response_model=list[EraSummary])
def list_eras(slug: str):
    """All eras for an artist."""
    artist = _store.get(slug)
    if not artist:
        raise HTTPException(status_code=404, detail=f"Artist '{slug}' not found")
    return [_era_to_summary(e) for e in artist.eras]


@app.get("/api/artists/{slug}/eras/{era_index}")
def get_era(slug: str, era_index: int):
    """Era detail with songs. era_index is 0-based."""
    artist = _store.get(slug)
    if not artist:
        raise HTTPException(status_code=404, detail=f"Artist '{slug}' not found")
    if era_index < 0 or era_index >= len(artist.eras):
        raise HTTPException(status_code=404, detail=f"Era index {era_index} out of range")

    era = artist.eras[era_index]
    return {
        "name": era.name,
        "description": era.description,
        "timeline": era.timeline,
        "art_url": era.art_url,
        "stats_raw": era.stats_raw,
        "stats": era.stats,
        "song_count": era.song_count,
        "version_count": era.version_count,
        "sections": [
            {"name": sec.name, "songs": sec.songs}
            for sec in era.sections
        ],
        "songs": era.songs,
    }


@app.get("/api/artists/{slug}/songs", response_model=list[SongDetail])
def list_songs(slug: str):
    """All songs across all eras (flat)."""
    artist = _store.get(slug)
    if not artist:
        raise HTTPException(status_code=404, detail=f"Artist '{slug}' not found")
    result = []
    for era in artist.eras:
        for song in era.songs:
            result.append(SongDetail(
                base_name=song.base_name,
                era_name=era.name,
                versions=song.versions,
            ))
    return result


@app.get("/api/search", response_model=list[SearchResult])
def search_songs(q: str = Query(..., min_length=1, description="Search query")):
    """Full-text search across all songs."""
    q_lower = q.lower()
    results = []
    for artist in _store.values():
        for era in artist.eras:
            for song in era.songs:
                # Search in base name
                if q_lower in song.base_name.lower():
                    results.append(SearchResult(
                        artist_name=artist.name,
                        artist_slug=artist.slug,
                        era_name=era.name,
                        song=song,
                    ))
                    continue
                # Search in version names and notes
                for v in song.versions:
                    if (q_lower in v.name.lower()
                            or (v.notes and q_lower in v.notes.lower())):
                        results.append(SearchResult(
                            artist_name=artist.name,
                            artist_slug=artist.slug,
                            era_name=era.name,
                            song=song,
                        ))
                        break
    return results


@app.post("/api/parse", response_model=ParseResponse)
def parse_tracker(req: ParseRequest):
    """Parse a tracker from URL and add to the in-memory store."""
    try:
        artist = fetch_and_parse(req.url, artist_name=req.artist_name)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse: {e}")

    _store[artist.slug] = artist
    return ParseResponse(
        name=artist.name,
        slug=artist.slug,
        era_count=len(artist.eras),
        total_songs=artist.total_songs,
        parse_metadata=artist.parse_metadata,
    )


@app.post("/api/cache/clear")
def api_clear_cache():
    """Clear the URL fetch cache."""
    count = clear_cache()
    return {"cleared": count}


# ---------------------------------------------------------------------------
# Streaming endpoints
# ---------------------------------------------------------------------------

class StreamRequest(BaseModel):
    url: str = Field(..., description="Original file-sharing link from the tracker")


class StreamInfo(BaseModel):
    streamable: bool
    stream_url: str | None = None


@app.post("/api/stream/resolve", response_model=StreamInfo)
def resolve_stream(req: StreamRequest):
    """Resolve a file-sharing link to a streamable audio URL.

    Returns whether the link is streamable and the resolved URL.
    """
    stream_url = resolve_stream_url(req.url)
    return StreamInfo(streamable=stream_url is not None, stream_url=stream_url)


@app.get("/api/stream")
def proxy_stream(url: str = Query(..., description="Original file-sharing link")):
    """Proxy an audio stream from a supported file-sharing host.

    Avoids CORS issues by fetching upstream and forwarding the audio bytes.
    The `url` parameter should be the original tracker link (e.g. pillows.su/f/xxx),
    not the resolved API URL — resolution happens server-side.
    """
    stream_url = resolve_stream_url(url)
    if stream_url is None:
        raise HTTPException(status_code=400, detail="URL is not from a supported streaming host")

    try:
        resp = stream_audio(stream_url)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    # Forward content-type and content-length if available
    headers: dict[str, str] = {}
    ct = resp.headers.get("content-type")
    if ct:
        headers["Content-Type"] = ct
    cl = resp.headers.get("content-length")
    if cl:
        headers["Content-Length"] = cl
    cd = resp.headers.get("content-disposition")
    if cd:
        headers["Content-Disposition"] = cd

    # Allow range requests for seeking
    headers["Accept-Ranges"] = "bytes"

    def _iter():
        try:
            for chunk in resp.iter_bytes(chunk_size=65536):
                yield chunk
        finally:
            resp.close()
            if hasattr(resp, "_client"):
                resp._client.close()

    return StreamingResponse(
        _iter(),
        status_code=200,
        headers=headers,
        media_type=ct or "application/octet-stream",
    )
