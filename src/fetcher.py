"""LeakSheet — URL fetcher for live Google Sheets tracker data.

Fetches HTML table data from Google Sheets /htmlview URLs and custom
tracker domains (e.g. yetracker.net).

Strategy:
1. Fetch the base htmlview page (JS-rendered, no table)
2. Extract sheet GIDs from the page
3. Fetch /htmlview/sheet?headers=true&gid=<GID> for server-rendered HTML with <table>
4. Extract artist name from <title>
5. Pass HTML to parser
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse, urlencode

import httpx

from src.models import Artist
from src.parser import parse_sheet


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 60.0  # Large trackers (Ye: 10MB) need time
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LeakSheet/1.0"

# Regex to extract sheet GIDs from the htmlview page JS
GID_PATTERN = re.compile(r"gid[=:]\s*[\"']?(\d+)")

# Regex to extract spreadsheet ID from Google Sheets URLs
SHEET_ID_PATTERN = re.compile(
    r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)"
)

# Regex to extract title
TITLE_PATTERN = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)

# Common title suffixes to strip when inferring artist name
TITLE_SUFFIXES = [
    " - Google Drive",
    " - Google Sheets",
    " - Google Docs",
    " Music Tracker",
    " Tracker [Currently in Use]",
    " Tracker",
]


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

def _normalize_url(url: str) -> str:
    """Ensure URL has a scheme."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _is_google_sheets_url(url: str) -> bool:
    """Check if URL is a Google Sheets URL."""
    return "docs.google.com/spreadsheets" in url


def _extract_sheet_id(url: str) -> str | None:
    """Extract the spreadsheet ID from a Google Sheets URL."""
    m = SHEET_ID_PATTERN.search(url)
    return m.group(1) if m else None


def _build_sheet_html_url(base_url: str, gid: str) -> str:
    """Build the /htmlview/sheet URL that returns server-rendered HTML.

    For Google Sheets: /spreadsheets/d/{id}/htmlview/sheet?headers=true&gid={gid}
    For custom domains: /htmlview/sheet?headers=true&gid={gid}
    """
    parsed = urlparse(base_url)

    if _is_google_sheets_url(base_url):
        sheet_id = _extract_sheet_id(base_url)
        if not sheet_id:
            raise ValueError(f"Cannot extract sheet ID from URL: {base_url}")
        path = f"/spreadsheets/d/{sheet_id}/htmlview/sheet"
    else:
        # Custom domain — append /htmlview/sheet
        path = "/htmlview/sheet"

    query = urlencode({"headers": "true", "gid": gid})
    return f"{parsed.scheme}://{parsed.netloc}{path}?{query}"


def _infer_artist_name(title: str) -> str:
    """Infer artist name from a page title.

    E.g. "Ye Tracker - Google Drive" → "Ye"
         "Baby Keem Music Tracker - Google Drive" → "Baby Keem"
         "Playboi Carti Tracker [Currently in Use] - Google Drive" → "Playboi Carti"
    """
    name = title.strip()
    for suffix in TITLE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    # Also strip leading emoji
    name = re.sub(r"^[\U0001f300-\U0001f9ff\s]+", "", name).strip()
    return name or title.strip()


# ---------------------------------------------------------------------------
# GID discovery
# ---------------------------------------------------------------------------

def _discover_gids(html: str) -> list[str]:
    """Extract sheet GIDs from the htmlview page HTML/JS.

    Returns list of GID strings found. The first one is typically the main sheet.
    """
    gids = GID_PATTERN.findall(html)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for gid in gids:
        if gid not in seen:
            seen.add(gid)
            unique.append(gid)
    return unique


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_sheet_html(
    url: str,
    *,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, str]:
    """Fetch the HTML table content from a Google Sheets tracker URL.

    Args:
        url: The tracker URL (Google Sheets htmlview or custom domain).
        gid: Specific sheet GID. If None, auto-discovered from the page.
        timeout: HTTP request timeout in seconds.

    Returns:
        Tuple of (html_content, page_title).

    Raises:
        ValueError: If no table data can be found.
        httpx.HTTPError: On network errors.
    """
    url = _normalize_url(url)

    client = httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )

    try:
        if gid:
            # Direct fetch with known GID
            sheet_url = _build_sheet_html_url(url, gid)
            r = client.get(sheet_url)
            r.raise_for_status()
            title_match = TITLE_PATTERN.search(r.text)
            title = title_match.group(1) if title_match else ""
            return r.text, title

        # Step 1: Fetch the base page to discover GIDs
        r = client.get(url)
        r.raise_for_status()
        base_html = r.text
        title_match = TITLE_PATTERN.search(base_html)
        title = title_match.group(1) if title_match else ""

        # If the base page already has tables (local file or direct sheet), return it
        if "<table" in base_html.lower():
            return base_html, title

        # Step 2: Discover GIDs
        gids = _discover_gids(base_html)

        if not gids:
            # Try gid=0 as fallback
            gids = ["0"]

        # Step 3: Fetch the sheet HTML with the first GID
        # Try each GID until we find one that works
        last_error = None
        for try_gid in gids:
            try:
                sheet_url = _build_sheet_html_url(url, try_gid)
                r = client.get(sheet_url)
                if r.status_code == 200 and "<table" in r.text.lower():
                    return r.text, title
            except Exception as e:
                last_error = e
                continue

        raise ValueError(
            f"No valid sheet data found at {url}. "
            f"Tried GIDs: {gids}. Last error: {last_error}"
        )
    finally:
        client.close()


def fetch_and_parse(
    url: str,
    *,
    artist_name: str | None = None,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Artist:
    """Fetch a tracker URL and parse it into an Artist model.

    Args:
        url: The tracker URL.
        artist_name: Override artist name (if None, inferred from page title).
        gid: Specific sheet GID (if None, auto-discovered).
        timeout: HTTP timeout in seconds.

    Returns:
        Parsed Artist object.
    """
    html, title = fetch_sheet_html(url, gid=gid, timeout=timeout)

    if not artist_name:
        artist_name = _infer_artist_name(title)

    artist = parse_sheet(html, artist_name)
    artist.source_url = url
    return artist


def fetch_links_file(
    links_path: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[Artist]:
    """Parse all URLs from a links.txt file.

    Args:
        links_path: Path to the links file (one URL per line).
        timeout: HTTP timeout per URL.

    Returns:
        List of parsed Artist objects.
    """
    path = Path(links_path)
    if not path.exists():
        return []

    artists: list[Artist] = []
    for line in path.read_text().splitlines():
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        try:
            artist = fetch_and_parse(url, timeout=timeout)
            artists.append(artist)
        except Exception as e:
            print(f"Warning: Failed to fetch {url}: {e}")

    return artists
