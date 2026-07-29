"""LeakSheet — Configuration and path management."""

import os
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

# Project root directory
ROOT_DIR = Path(__file__).resolve().parent.parent

# Shared User-Agent for all backend HTTP traffic (sheet fetches, stream
# proxying, metadata lookups). The image proxy uses its own browser-like UA —
# see api._get_proxy_client.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LeakSheet/1.0"

# Default trackers directory
TRACKERS_DIR = ROOT_DIR / "Trackers"

# TrackerHub — community-maintained master sheet listing artist trackers.
# Backs the GET /trackers discovery endpoint. The gid pins the single tab
# that holds the tracker list, so the page contains exactly one table.
TRACKERHUB_URL = (
    "https://docs.google.com/spreadsheets/u/0/d/"
    "1Z8aANbxXbnUGoZPRvJfWL3gz6jrzPPrwVt3d0c1iJ_4/htmlview/sheet"
    "?headers=true&gid=1884837542"
)

# ---------------------------------------------------------------------------
# Sheet-fetch host allowlist
# ---------------------------------------------------------------------------
#
# POST /sheet takes a URL from the caller and fetches it, so without this the
# backend is an SSRF sink: cloud metadata (169.254.169.254) and RFC1918 hosts
# are reachable, any internal page holding a <table> comes back parsed, and
# the distinct 404/502/403 mappings make it an internal port scanner.
#
# Almost every tracker is on docs.google.com (413 of the 414 in the 2026-07-20
# TrackerHub sweep). The rest are custom domains, so the allowlist is seeded
# with the known ones and extended at runtime from the TrackerHub feed — a
# newly listed tracker works without a deploy. LEAKSHEET_EXTRA_SHEET_HOSTS
# (comma-separated) is the operator escape hatch.
_SHEET_HOST_SEED = frozenset({
    "docs.google.com",
    "drive.google.com",
    "yetracker.net",          # README's CLI example
    "deftonestracker.net",    # only non-Google host in the 2026-07-20 sweep
})

# Hosts harvested from the TrackerHub feed, and when that last happened.
_tracker_hosts: set[str] = set()
_tracker_hosts_at: float = 0.0

# Don't let a miss-triggered refresh become an amplification vector.
TRACKER_HOST_REFRESH_INTERVAL = 900.0  # 15 minutes


def _env_sheet_hosts() -> set[str]:
    raw = os.environ.get("LEAKSHEET_EXTRA_SHEET_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def register_tracker_hosts(urls: Iterable[str]) -> int:
    """Record the hosts of TrackerHub-listed trackers as fetchable.

    Returns the number of hosts now known. Called whenever the feed is
    parsed, so the normal /trackers path keeps the allowlist warm.
    """
    global _tracker_hosts_at
    for url in urls:
        host = urlparse(url).hostname
        if host:
            _tracker_hosts.add(host.lower())
    _tracker_hosts_at = time.time()
    return len(_tracker_hosts)


def tracker_hosts_are_stale() -> bool:
    """True when a miss is worth one TrackerHub refresh."""
    return time.time() - _tracker_hosts_at > TRACKER_HOST_REFRESH_INTERVAL


def sheet_host_allowed(host: str | None) -> bool:
    """True if *host* may be fetched by the sheet pipeline."""
    if not host:
        return False
    host = host.lower()
    return (
        host in _SHEET_HOST_SEED
        or host in _tracker_hosts
        or host in _env_sheet_hosts()
    )


# Known tracker files and their artist names
KNOWN_TRACKERS: dict[str, str] = {
    "Baby Keem Music Tracker - Google Drive": "Baby Keem",
    "Kendrick Lamar Music Tracker - Google Drive": "Kendrick Lamar",
    "Playboi Carti Tracker [Currently in Use] - Google Drive": "Playboi Carti",
    "Ye Tracker - Google Drive": "Ye",
}


def discover_trackers(trackers_dir: Path | None = None) -> list[tuple[str, Path]]:
    """Discover all tracker files in the given directory.

    Returns list of (artist_name, sheet_html_path) tuples.
    """
    directory = trackers_dir or TRACKERS_DIR
    results = []

    for tracker_name, artist_name in KNOWN_TRACKERS.items():
        sheet_path = directory / f"{tracker_name}_files" / "sheet.html"
        if sheet_path.exists():
            results.append((artist_name, sheet_path))

    # Also discover any unknown tracker directories
    if directory.exists():
        for child in sorted(directory.iterdir()):
            if child.is_dir() and child.name.endswith("_files"):
                sheet_path = child / "sheet.html"
                if sheet_path.exists():
                    base_name = child.name.removesuffix("_files")
                    if base_name not in KNOWN_TRACKERS:
                        # Use the directory name as artist name
                        artist_name = base_name.replace(" - Google Drive", "").strip()
                        results.append((artist_name, sheet_path))

    return results


# Column name normalization — maps various header text to canonical field names.
# Covers 400+ tracker variants observed in the wild.
COLUMN_ALIASES: dict[str, str] = {
    # Core columns (present in nearly all trackers)
    "era": "era",
    "name": "name",
    "title": "name",              # Billie Eilish, Childish Gambino, Travis Scott
    "song name": "name",          # XXXTENTACION
    "song title": "name",
    "song": "name",               # 2026-07-20 sweep (3 trackers)
    "track titles": "name",       # SosMula ("Track Titles:")
    "track title": "name",
    "notes": "notes",
    "notes & information": "notes",
    "track number / info": "notes",  # Yuno Miles
    "info": "notes",
    "description": "notes",

    # Track length variants
    "track length": "track_length",
    "length": "track_length",      # Billie Eilish, Gucci Mane, etc.
    "track duration": "track_length",
    "duration": "track_length",

    # Dates
    "file date": "file_date",
    "creation date": "file_date",  # Kid Cudi
    "date created": "file_date",
    "year": "file_date",           # Avicii
    # Bare 'Date' means the surfaced/leaked date in most trackers
    # (user-confirmed 2026-07-20; 19 trackers in the TrackerHub sweep).
    "date": "leak_date",
    "leak date": "leak_date",
    "release date": "leak_date",   # Gucci Mane, Yuno Miles
    "release/leaked date": "leak_date",  # SosMula (2026-07-20 sweep)
    "obtained on:": "leak_date",   # Wu-Tang Clan
    "obtained on": "leak_date",

    # Availability
    "available length": "available_length",
    "currently available": "available_length",  # Kid Cudi, Chief Keef
    "available?": "available_length",             # Yung Lean
    "what's available?": "available_length",      # Travis Scott
    "available": "available_length",
    "song status": "available_length",            # XXXTENTACION
    "status": "available_length",
    "availability": "available_length",          # Lil Uzi Vert
    "portion": "available_length",                # Template variant

    # Quality
    "quality": "quality",

    # Links
    "link(s)": "links",
    "links": "links",
    "link": "links",
    "download(s)": "links",       # XXXTENTACION
    "downloads": "links",
    "download": "links",
    "og link(s)": "links",        # XXXTENTACION (secondary links)
    "main link": "links",         # Juice WRLD
    "alternate links": "alt_links",  # Juice WRLD
    "alternate link": "alt_links",
    "alt links": "alt_links",
    "alt link": "alt_links",
    "mirror links": "alt_links",
    "mirror link": "alt_links",
    "mirrors": "alt_links",
    "mirror": "alt_links",

    # Streaming availability (Yes/No) → SongVersion.streaming
    "streaming": "streaming",
    "streaming?": "streaming",
    "in circulation": "available_length",  # Yung Lean

    # Evidence/provenance links (Travis Scott tracker)
    "sources": "sources",
    "source": "sources",
    "source(s)": "sources",

    # Type variants
    "type": "type",
    "track type": "type",          # XXXTENTACION
    "song type": "type",

    # Recording date variants
    "date of recording": "date_of_recording",  # Carti
    "recording date": "date_of_recording",      # Gucci Mane
    "record date": "date_of_recording",         # 2026-07-20 sweep (4 trackers)

    # Dedicated credit columns (user-confirmed 2026-07-20 sweep mappings).
    # Producer column fills SongVersion.producers only when the name-cell
    # '(prod. …)' credit didn't already set it; Artist columns land in the
    # additive credited_artists field (the row's performer, NOT a feature).
    "producer": "producers_col",
    "producers": "producers_col",
    "artist": "credited_artists",
    "artists": "credited_artists",
    "credited artist": "credited_artists",
    "credited artists": "credited_artists",

    # Dedicated original-filename columns → og_filenames (merged with the
    # 'OG Filename:' notes convention).
    "file name": "og_filename_col",
    "filename": "og_filename_col",
    "instrumental name": "og_filename_col",
}
