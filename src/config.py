"""LeakSheet — Configuration and path management."""

import os
import time
import tomllib
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent

# pyproject.toml is the one version source; the image copies it next to src/.
VERSION = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())["project"]["version"]

# Shared User-Agent for backend HTTP traffic. The image proxy uses its own
# browser-like UA (api._get_proxy_client).
USER_AGENT = f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LeakSheet/{VERSION}"

TRACKERS_DIR = ROOT_DIR / "Trackers"

# ArtistGrid: community-maintained tracker registry (CSV) behind GET /trackers.
# src/tracker_seed.py is the fallback when it is unreachable.
ARTISTGRID_URL = "https://artists.artistgrid.cx/artists.csv"

# SSRF guard for POST /sheet: see docs/decisions.md::config.py — the /sheet host allowlist
_SHEET_HOST_SEED = frozenset({
    "docs.google.com",
    "drive.google.com",
    "yetracker.net",          # README's CLI example
    "deftonestracker.net",    # non-Google tracker host
    "franktracker.net",       # non-Google host in the built-in seed (src/tracker_seed.py)
    "tylertracker.net",       # self-hosted covers; the image proxy trusts only this seed
    "asaprockytracker.net",   # self-hosted covers; the image proxy ignores feed-listed hosts
})

# Hosts harvested from the ArtistGrid feed, and when that last happened.
_tracker_hosts: set[str] = set()
_tracker_hosts_at: float = 0.0

# Don't let a miss-triggered refresh become an amplification vector.
TRACKER_HOST_REFRESH_INTERVAL = 900.0  # 15 minutes


def _env_sheet_hosts() -> set[str]:
    raw = os.environ.get("LEAKSHEET_EXTRA_SHEET_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def register_tracker_hosts(urls: Iterable[str]) -> int:
    """Record the hosts of ArtistGrid-listed trackers as fetchable.

    Returns the number of hosts now known.
    """
    global _tracker_hosts_at
    for url in urls:
        host = urlparse(url).hostname
        if host:
            _tracker_hosts.add(host.lower())
    _tracker_hosts_at = time.time()
    return len(_tracker_hosts)


def tracker_hosts_are_stale() -> bool:
    """True when a miss is worth one ArtistGrid refresh."""
    return time.time() - _tracker_hosts_at > TRACKER_HOST_REFRESH_INTERVAL


def curated_host_allowed(host: str | None) -> bool:
    """True if *host* is in the built-in seed or LEAKSHEET_EXTRA_SHEET_HOSTS.

    Ignores feed-harvested hosts: see docs/decisions.md::config.py::curated_host_allowed.
    """
    if not host:
        return False
    host = host.lower()
    return host in _SHEET_HOST_SEED or host in _env_sheet_hosts()

# Image-proxy reach (SSRF allowlist): Google's image CDNs plus the curated hosts.
_IMAGE_ALLOWED_DOMAINS = {
    # Misc-tab YouTube thumbnails (MiscLinkClassifier.thumbnailURL); the client
    # routes every thumbnail through this proxy.
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


def _image_host_allowed(url: str) -> bool:
    """Hosts the image proxy may fetch from.

    Google's image CDNs, plus the curated tracker seed and
    LEAKSHEET_EXTRA_SHEET_HOSTS (self-hosted trackers serve covers from their own
    origin). Deliberately NOT the ArtistGrid-harvested hosts /sheet accepts: see
    docs/decisions.md::config.py::curated_host_allowed.
    """
    if _is_allowed_domain(url, _IMAGE_ALLOWED_DOMAINS, _IMAGE_ALLOWED_PARENT_DOMAINS):
        return True
    try:
        return curated_host_allowed(urlparse(url).hostname)
    except ValueError:  # unclosed "[" in the host
        return False


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
    except ValueError:  # an unparseable URL is never allowed
        return False


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
                        artist_name = base_name.replace(" - Google Drive", "").strip()
                        results.append((artist_name, sheet_path))

    return results


# Maps normalized header text to canonical field names.
COLUMN_ALIASES: dict[str, str] = {
    # Core columns (present in nearly all trackers)
    "era": "era",
    "project": "era",             # Overlord's Lil Uzi Vert discography tracker
    # Carti's Released tab ships both; the first in header order wins, which
    # is the release era — it leads on the sheet.
    "rel. era": "era",
    "rec. era": "era",
    "name": "name",
    "title": "name",              # Billie Eilish, Childish Gambino, Travis Scott
    "song name": "name",          # XXXTENTACION
    "song title": "name",
    "song": "name",
    "track titles": "name",       # SosMula ("Track Titles:")
    "track title": "name",
    "notes": "notes",
    "notes & information": "notes",
    "track number / info": "notes",  # Yuno Miles
    "info": "notes",
    "description": "notes",
    "additional information": "notes",
    "info / notes": "notes",

    # Track length variants
    "track length": "track_length",
    "length": "track_length",      # Billie Eilish, Gucci Mane, etc.
    "track duration": "track_length",
    "duration": "track_length",
    "full length": "track_length",
    "lenght": "track_length",       # real, recurring misspelling in the wild


    # Dates
    "file date": "file_date",
    "creation date": "file_date",  # Kid Cudi
    "date created": "file_date",
    "year": "file_date",           # Avicii
    "date made": "file_date",
    # Bare 'Date' means the surfaced/leaked date in most trackers (user-confirmed).
    "date": "leak_date",
    "leak date": "leak_date",
    "release date": "leak_date",   # Gucci Mane, Yuno Miles
    "release/leaked date": "leak_date",  # SosMula
    "obtained on:": "leak_date",   # Wu-Tang Clan
    "obtained on": "leak_date",
    # Both mean "when it got out", same as a leak date (user-confirmed).
    "surface date": "leak_date",
    "surfaced date": "leak_date",
    "og file leak date": "leak_date",
    # Prefix matching only fires on glued header text, so real "date"-prefixed
    # headers must be listed explicitly.
    "leaked": "leak_date",
    "date leaked": "leak_date",
    "date added": "leak_date",
    "date of release": "leak_date",
    "date or art": "leak_date",     # Haunted Mound — one column, either value

    # When a snippet was first previewed — deliberately NOT leak_date: a
    # preview predates (and often never becomes) a leak (user-confirmed).
    "first preview": "preview_date",
    "preview date": "preview_date",
    "previewed": "preview_date",

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
    "download / link": "links",
    "snippet/song link": "links",
    "og link(s)": "links",        # XXXTENTACION (secondary links)
    "main link": "links",         # Juice WRLD
    "alternate links": "alt_links",  # Juice WRLD
    "alternate link": "alt_links",
    "alt links": "alt_links",
    "alt link": "alt_links",
    # The normaliser strips only a trailing colon, so the dotted form needs its own entry.
    "alt. links": "alt_links",
    "alt. link": "alt_links",
    "mirror links": "alt_links",
    "mirror link": "alt_links",
    "mirrors": "alt_links",
    "mirror": "alt_links",

    # Streaming availability (Yes/No) → SongVersion.streaming
    "streaming": "streaming",
    "streaming?": "streaming",
    "on streaming": "streaming",
    "on streaming?": "streaming",
    "in circulation": "available_length",  # Yung Lean
    "currently avalible": "available_length",  # sic

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
    "record date": "date_of_recording",
    "shoot date": "date_of_recording",          # music-video tabs (user-confirmed)
    "date recorded": "date_of_recording",       # a recording date, not leak_date
    "recorded": "date_of_recording",

    # Dedicated credit columns — see docs/decisions.md::config.py::COLUMN_ALIASES
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
    "instrumental file": "og_filename_col",
}

# Headers deliberately left unmapped: see docs/decisions.md::config.py::COLUMN_ALIASES — unmapped headers
