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

import asyncio
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlencode

import httpx

logger = logging.getLogger(__name__)

from src.models import Artist
from src.parser import apply_art_tab_images, parse_art_tab, parse_sheet, _era_match_key


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 60.0  # Large trackers (Ye: 10MB) need time
DEFAULT_CACHE_TTL = 3600  # 1 hour default cache
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LeakSheet/1.0"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

# Regex to extract sheet GIDs from the htmlview page JS
GID_PATTERN = re.compile(r"gid[=:]\s*[\"']?(\d+)")

# Regex to extract (name, gid) pairs from the items.push() JS in htmlview pages.
# Google Sheets embeds tab metadata as:
#   items.push({name: "Tab Name", pageUrl: "...", gid: "12345", ...});
_TAB_ITEMS_PATTERN = re.compile(
    r'\{name:\s*"([^"]+)"[^}]*?gid:\s*"(\d+)"',
)

# Art tab name keywords (after stripping emojis and normalising whitespace)
_ART_TAB_NAMES = frozenset({"art", "album art", "cover art", "artwork", "arts", "album arts"})

# Tab names that identify the main unreleased/leaks tracker sheet.
# When discovered, this tab is tried first before any other GIDs so that
# trackers with a "Recent" landing tab (e.g. Travis Scott 2.0) don't fool
# the fetcher into treating the small Recent sheet as the primary data.
_UNRELEASED_TAB_NAMES = frozenset({
    "unreleased", "leaks", "leaked", "unreleased songs",
    "leaked songs", "all unreleased", "all unreleased songs",
    "all leaks", "main", "tracker",
})

# Regex to extract spreadsheet ID from Google Sheets URLs
# Handles both /d/ID and /u/N/d/ID paths (user-scoped URLs)
SHEET_ID_PATTERN = re.compile(
    r"docs\.google\.com/spreadsheets(?:/u/\d+)?/d/([A-Za-z0-9_-]+)"
)

# Regex to extract GID from URL fragment (#gid=...) or query param (?gid=...)
_URL_GID_PATTERN = re.compile(r"[#?&]gid=(\d+)")

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
    " Leak Tracker",
    " Leaks Tracker",
]

# Emoji pattern for stripping decorative emoji from tab names
_EMOJI_RE = re.compile(
    r"[\U0001f300-\U0001f9ff\U00002600-\U000027bf\U00002b50\ufe0f\u200d]+"
)

# Minimum era count required before accepting a GID as the primary tracker tab.
# Prevents small "Recent" or landing tabs from being chosen over the main sheet.
_MIN_ERAS_FOR_VALID_GID = 5

# Prefixes to strip from inferred artist names (e.g. "Updated Lil Uzi Vert")
TITLE_PREFIXES = [
    "Updated ",
    "New ",
    "Official ",
]


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

def _normalize_url(url: str) -> str:
    """Ensure URL has a scheme and normalize Google Sheets paths to /htmlview.

    Google Sheets URLs come in many forms (/edit, /view, /pubhtml, etc.).
    The /htmlview endpoint is the only one that:
      1. Returns lightweight HTML (no heavy JS app shell)
      2. Exposes GIDs for all sheet tabs in the page source
    Without this normalization, /edit URLs return the default tab's HTML
    directly, bypassing GID discovery and missing the main tracker tab.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Normalize Google Sheets URLs to /htmlview for reliable GID discovery
    if _is_google_sheets_url(url):
        sheet_id = _extract_sheet_id(url)
        if sheet_id:
            parsed = urlparse(url)
            url = f"{parsed.scheme}://{parsed.netloc}/spreadsheets/d/{sheet_id}/htmlview"

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
         "Updated Lil Uzi Vert Tracker - Google Drive" → "Lil Uzi Vert"
         "The Guy From Degrassi Tracker (reup 12.29.25) - Google Drive" → "Drake"
    """
    name = title.strip()

    # Step 1: Strip known suffixes (" - Google Drive", " Tracker", etc.)
    for suffix in TITLE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()

    # Step 1b: Strip "Tracker 2.0" / "Tracker v3" style version suffixes
    # (e.g. "Travis Scott Tracker 2.0" → "Travis Scott Tracker" → "Travis Scott")
    name = re.sub(r"\s+Tracker\s+[\d.v]+\s*$", "", name, flags=re.IGNORECASE).strip()
    # Re-apply suffix stripping after version removal
    for suffix in TITLE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()

    # Step 2: Strip trailing parenthetical metadata like "(reup 12.29.25)"
    # that prevents suffix stripping on the first pass
    paren_match = re.search(r"\s*\([^)]*\)\s*$", name)
    if paren_match:
        stripped = name[: paren_match.start()].strip()
        # Re-apply suffix stripping on the cleaned name
        for suffix in TITLE_SUFFIXES:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)].strip()
        if stripped:
            name = stripped

    # Step 3: Strip known prefixes ("Updated ", etc.)
    for prefix in TITLE_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()

    # Step 4: Strip leading emoji
    name = re.sub(r"^[\U0001f300-\U0001f9ff\s]+", "", name).strip()

    # Step 5: Map well-known tracker aliases to real artist names
    _TRACKER_ALIASES = {
        "the guy from degrassi": "Drake",
    }
    name_lower = name.lower()
    if name_lower in _TRACKER_ALIASES:
        name = _TRACKER_ALIASES[name_lower]

    return name or title.strip()


# ---------------------------------------------------------------------------
# GID discovery
# ---------------------------------------------------------------------------

def _extract_gid_from_url(url: str) -> str | None:
    """Extract a sheet GID from the URL fragment or query params.

    Handles: #gid=123, ?gid=123, &gid=123
    """
    m = _URL_GID_PATTERN.search(url)
    return m.group(1) if m else None


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


def _discover_named_tabs(html: str) -> dict[str, str]:
    """Extract {gid: tab_name} mapping from htmlview page HTML/JS.

    Google Sheets htmlview embeds tab metadata as JS items.push() calls:
      items.push({name: "Art", pageUrl: "...", gid: "1234", ...});
    Tab names may contain leading emoji (e.g. "\U0001f5bc\ufe0f Art").
    """
    result: dict[str, str] = {}
    for name, gid in _TAB_ITEMS_PATTERN.findall(html):
        name = name.strip()
        if name and gid:
            result.setdefault(gid, name)
    return result


def _get_unreleased_tab_gid(named_tabs: dict[str, str]) -> str | None:
    """Return the GID of the main unreleased/leaks tab if one exists.

    Strips emoji and normalises whitespace before comparing against
    _UNRELEASED_TAB_NAMES. Used to prefer the primary tracker sheet over
    landing/recent tabs like Travis Scott's "Recent" sheet.
    """
    for gid, name in named_tabs.items():
        clean = _EMOJI_RE.sub(" ", name).strip().lower()
        clean = re.sub(r"\s+", " ", clean)
        if clean in _UNRELEASED_TAB_NAMES:
            return gid
    return None


def _get_art_tab_gid(named_tabs: dict[str, str]) -> str | None:
    """Return the GID of the Art tab if one is present, else None.

    Strips emoji and normalises whitespace before comparing against the
    known art-tab keyword set ({"art", "album art", "cover art", ...}).
    """
    for gid, name in named_tabs.items():
        clean = _EMOJI_RE.sub(" ", name).strip().lower()
        clean = re.sub(r"\s+", " ", clean)
        if clean in _ART_TAB_NAMES:
            return gid
    return None


def _infer_artist_from_sheet(html: str) -> str | None:
    """Try to infer artist name from sheet content (header row era names).

    For multi-sheet workbooks, the page <title> may not match the actual
    sheet content. This looks at era headers for clues.
    """
    # Look for sheet tab names in the HTML
    # Google Sheets htmlview includes sheet names in the page
    tab_pattern = re.compile(r'class="[^"]*sheet-tab[^"]*"[^>]*>([^<]+)<', re.I)
    tabs = tab_pattern.findall(html)
    if tabs:
        # The sheet tab name often contains the artist name
        for tab in tabs:
            cleaned = tab.strip()
            for suffix in TITLE_SUFFIXES:
                if cleaned.endswith(suffix):
                    cleaned = cleaned[:-len(suffix)].strip()
            if cleaned and len(cleaned) > 1:
                return cleaned
    return None


# ---------------------------------------------------------------------------
# File-based cache
# ---------------------------------------------------------------------------

def _cache_key(url: str) -> str:
    """SHA-256 hash of URL as cache filename."""
    return hashlib.sha256(url.encode()).hexdigest()


def _get_cached(url: str, cache_ttl: float = DEFAULT_CACHE_TTL) -> tuple[str, str] | None:
    """Return (html, title) from cache if fresh, else None."""
    key = _cache_key(url)
    cache_file = CACHE_DIR / f"{key}.html"
    meta_file = CACHE_DIR / f"{key}.meta.json"

    if cache_file.exists() and meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            if time.time() - meta.get("timestamp", 0) < cache_ttl:
                return cache_file.read_text(encoding="utf-8"), meta.get("title", "")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cache read failed for %s: %s", url[:80], e)
    return None


def _set_cache(url: str, html: str, title: str) -> None:
    """Write HTML and metadata to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url)
    (CACHE_DIR / f"{key}.html").write_text(html, encoding="utf-8")
    (CACHE_DIR / f"{key}.meta.json").write_text(
        json.dumps({"url": url, "title": title, "timestamp": time.time()}),
        encoding="utf-8",
    )


def _get_cached_parsed(url: str, cache_ttl: float = DEFAULT_CACHE_TTL) -> Artist | None:
    """Return cached Artist from parsed JSON if fresh, else None."""
    key = _cache_key(url)
    parsed_file = CACHE_DIR / f"{key}.parsed.json"
    meta_file = CACHE_DIR / f"{key}.meta.json"
    if parsed_file.exists() and meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            if time.time() - meta.get("timestamp", 0) < cache_ttl:
                data = json.loads(parsed_file.read_text(encoding="utf-8"))
                return Artist.parse_obj(data)
        except (json.JSONDecodeError, OSError, Exception) as e:
            logger.warning("Parsed cache read failed for %s: %s", url[:80], e)
    return None


def _set_cached_parsed(url: str, artist: Artist) -> None:
    """Write parsed Artist JSON to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url)
    try:
        data = artist.dict()
        (CACHE_DIR / f"{key}.parsed.json").write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
    except (OSError, TypeError) as e:
        logger.warning("Failed to cache parsed result: %s", e)


def clear_cache() -> int:
    """Remove all cached files. Returns number of files deleted."""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.iterdir():
        f.unlink()
        count += 1
    return count


# ---------------------------------------------------------------------------
# Shared parse helpers (used by both sync and async paths)
# ---------------------------------------------------------------------------

def _resolve_artist_name(html: str, title: str, artist_name_override: str | None) -> str:
    """Determine the artist name from page HTML and title, with an optional override.

    Priority:
    1. ``artist_name_override`` if provided.
    2. Name scraped directly from the sheet (first non-header name-column value).
    3. Name inferred from the page ``<title>`` after stripping common suffixes.
    """
    name = artist_name_override
    if not name:
        name = _infer_artist_name(title)
        sheet_artist = _infer_artist_from_sheet(html)
        if sheet_artist and sheet_artist.lower() != name.lower():
            name = sheet_artist
    return name


def _prioritize_gids(
    base_html: str, gids: list[str]
) -> tuple[list[str], str | None, str | None]:
    """Reorder GIDs so the main tracker tab is tried first.

    Returns (reordered_gids, art_gid, unreleased_gid).
    Moves the identified "Unreleased" tab GID to the front when found,
    so trackers with a landing/recent tab (e.g. Travis Scott 2.0) don't
    get stuck on the wrong sheet.
    """
    named_tabs = _discover_named_tabs(base_html)
    art_gid = _get_art_tab_gid(named_tabs)
    unreleased_gid = _get_unreleased_tab_gid(named_tabs)
    if unreleased_gid and unreleased_gid in gids:
        logger.debug("Unreleased tab detected (gid=%s) — trying first", unreleased_gid)
        gids = [unreleased_gid] + [g for g in gids if g != unreleased_gid]
    return gids, art_gid, unreleased_gid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_sheet_html(
    url: str,
    *,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    use_cache: bool = True,
) -> tuple[str, str]:
    """Fetch the HTML table content from a Google Sheets tracker URL.

    Args:
        url: The tracker URL (Google Sheets htmlview or custom domain).
        gid: Specific sheet GID. If None, auto-discovered from the page.
        timeout: HTTP request timeout in seconds.
        cache_ttl: Cache time-to-live in seconds (0 to disable).
        use_cache: Whether to use file-based caching.

    Returns:
        Tuple of (html_content, page_title).

    Raises:
        ValueError: If no table data can be found.
        httpx.HTTPError: On network errors.
    """
    # Extract GID from original URL BEFORE normalization strips query/fragment
    if not gid:
        gid = _extract_gid_from_url(url)

    url = _normalize_url(url)

    # Check cache first
    if use_cache and cache_ttl > 0:
        cached = _get_cached(url, cache_ttl)
        if cached is not None:
            return cached

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
            if use_cache:
                _set_cache(url, r.text, title)
            return r.text, title

        # Step 1: Fetch the base page to discover GIDs
        r = client.get(url)
        r.raise_for_status()
        base_html = r.text
        title_match = TITLE_PATTERN.search(base_html)
        title = title_match.group(1) if title_match else ""

        # If the base page already has tables (local file or direct sheet), return it
        if "<table" in base_html.lower():
            if use_cache:
                _set_cache(url, base_html, title)
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
                    if use_cache:
                        _set_cache(url, r.text, title)
                    return r.text, title
            except (httpx.HTTPError, ValueError, KeyError) as e:
                last_error = e
                continue

        raise NoTablesError(
            f"No valid sheet data found at {url}. "
            f"Tried GIDs: {gids}. Last error: {last_error}"
        )
    except NoTablesError:
        raise
    except httpx.TimeoutException as e:
        raise NetworkError(f"Request timed out: {e}") from e
    except httpx.ConnectError as e:
        raise NetworkError(f"Cannot connect to {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise AccessDeniedError(f"Access denied (403): {url}") from e
        if e.response.status_code == 404:
            raise InvalidURLError(f"URL not found (404): {url}") from e
        raise NetworkError(f"HTTP {e.response.status_code}: {e}") from e
    finally:
        client.close()


def fetch_and_parse(
    url: str,
    *,
    artist_name: str | None = None,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    use_cache: bool = True,
) -> Artist:
    """Fetch a tracker URL and parse it into an Artist model.

    Args:
        url: The tracker URL.
        artist_name: Override artist name (if None, inferred from page title).
        gid: Specific sheet GID (if None, auto-discovered).
        timeout: HTTP timeout in seconds.
        cache_ttl: Cache TTL in seconds.
        use_cache: Whether to use file-based caching.

    Returns:
        Parsed Artist object.
    """
    # Extract GID from original URL BEFORE normalization strips query/fragment
    if not gid:
        gid = _extract_gid_from_url(url)
    url_norm = _normalize_url(url)

    # Check parsed result cache first (skip entire parse pipeline)
    if use_cache and cache_ttl > 0:
        cached_artist = _get_cached_parsed(url_norm, cache_ttl)
        if cached_artist is not None:
            cached_artist.source_url = url
            return cached_artist

    # If a specific GID was requested, try it first.
    # If it produces 0 eras, fall through to GID discovery.
    if gid:
        try:
            html, title = fetch_sheet_html(url, gid=gid, timeout=timeout,
                                            cache_ttl=cache_ttl, use_cache=use_cache)
            name = _resolve_artist_name(html, title, artist_name)
            artist = parse_sheet(html, name)
            if artist.eras:
                # Before returning, check if this page reveals a better
                # "Unreleased" tab (e.g. Travis Scott's "Recents" landing tab).
                # The GID-specific HTML embeds all tab names via items.push() JS,
                # so no extra request is needed.
                named_tabs = _discover_named_tabs(html)
                unreleased_tab_gid = _get_unreleased_tab_gid(named_tabs)
                if not unreleased_tab_gid or unreleased_tab_gid == gid:
                    artist.source_url = url
                    if use_cache:
                        _set_cached_parsed(url_norm, artist)
                    return artist
                # A better "Unreleased" tab exists — fall through to full discovery
            # GID produced 0 eras — fall through to GID discovery below
        except (FetchError, httpx.HTTPError, ValueError):
            pass  # GID failed — fall through to GID discovery

    # No specific GID — discover all GIDs and try them.
    # The first GID with tables might be a landing page (Doja Cat, Sabrina
    # Carpenter, etc.), so we try multiple GIDs and pick the best result.
    client = httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )

    try:
        # Step 1: Fetch the base page to discover GIDs
        r = client.get(url_norm)
        r.raise_for_status()
        base_html = r.text
        title_match = TITLE_PATTERN.search(base_html)
        title = title_match.group(1) if title_match else ""

        # If the base page already has tables, try parsing directly
        if "<table" in base_html.lower():
            name = _resolve_artist_name(base_html, title, artist_name)
            artist = parse_sheet(base_html, name)
            if artist.eras:
                artist.source_url = url
                if use_cache:
                    _set_cache(url_norm, base_html, title)
                    _set_cached_parsed(url_norm, artist)
                return artist

        # Step 2: Discover GIDs and prioritize tracker tab
        gids = _discover_gids(base_html)
        if not gids:
            gids = ["0"]

        gids, art_gid, unreleased_gid = _prioritize_gids(base_html, gids)

        # Step 3: Try each GID, pick the one that produces the most eras
        best_artist: Artist | None = None
        best_eras = 0
        best_html = ""

        for try_gid in gids:
            try:
                sheet_url = _build_sheet_html_url(url_norm, try_gid)
                logger.debug("Trying GID %s (%s)", try_gid, sheet_url)

                # Check cache for this specific GID URL
                if use_cache and cache_ttl > 0:
                    cached = _get_cached(sheet_url, cache_ttl)
                    if cached is not None:
                        sheet_html, _ = cached
                    else:
                        resp = client.get(sheet_url)
                        if resp.status_code != 200 or "<table" not in resp.text.lower():
                            continue
                        sheet_html = resp.text
                        if use_cache:
                            _set_cache(sheet_url, sheet_html, title)
                else:
                    resp = client.get(sheet_url)
                    if resp.status_code != 200 or "<table" not in resp.text.lower():
                        continue
                    sheet_html = resp.text

                name = _resolve_artist_name(sheet_html, title, artist_name)
                candidate = parse_sheet(sheet_html, name)

                n_eras = len(candidate.eras)
                n_songs = sum(
                    len(section.songs)
                    for era in candidate.eras
                    for section in era.sections
                )

                logger.debug("GID %s → %d eras, %d songs", try_gid, n_eras, n_songs)
                if n_eras > best_eras or (n_eras == best_eras and n_songs > 0):
                    best_eras = n_eras
                    best_artist = candidate
                    best_html = sheet_html

                # Unreleased tab wins as long as it has at least 1 era —
                # prevents Recents/landing tabs from outcompeting it on era count.
                if try_gid == unreleased_gid and n_eras >= 1:
                    logger.debug("Selected unreleased GID %s (%d eras)", try_gid, n_eras)
                    break
                # Otherwise stop once we have a solid result (≥5 eras)
                elif n_eras >= _MIN_ERAS_FOR_VALID_GID:
                    break

            except (httpx.HTTPError, ValueError, KeyError):
                logger.debug("GID %s fetch/parse failed, trying next", try_gid)
                continue

        if best_artist and best_eras > 0:
            best_artist.source_url = url
            # Fetch Art tab and upgrade era.art_url to high-quality images
            if art_gid:
                try:
                    art_sheet_url = _build_sheet_html_url(url_norm, art_gid)
                    art_cached = (
                        _get_cached(art_sheet_url, cache_ttl)
                        if use_cache and cache_ttl > 0
                        else None
                    )
                    if art_cached:
                        art_html = art_cached[0]
                    else:
                        art_resp = client.get(art_sheet_url)
                        if art_resp.status_code == 200 and "<table" in art_resp.text.lower():
                            art_html = art_resp.text
                            if use_cache:
                                _set_cache(art_sheet_url, art_html, title)
                        else:
                            art_html = ""
                    if art_html:
                        art_map = parse_art_tab(art_html)
                        if art_map:
                            apply_art_tab_images(best_artist, art_map)
                except (httpx.HTTPError, ValueError, KeyError):
                    pass  # Art tab fetch failed — not critical, keep existing art_url
            # Cache the best result under the original URL
            if use_cache and best_html:
                _set_cache(url_norm, best_html, title)
            if use_cache:
                _set_cached_parsed(url_norm, best_artist)
            return best_artist

        # Nothing worked — return whatever the first GID gave us
        html, title = fetch_sheet_html(url, timeout=timeout,
                                        cache_ttl=cache_ttl, use_cache=use_cache)
        name = _resolve_artist_name(html, title)
        artist = parse_sheet(html, name)
        artist.source_url = url
        if use_cache:
            _set_cached_parsed(url_norm, artist)
        return artist

    except httpx.TimeoutException as e:
        raise NetworkError(f"Request timed out: {e}") from e
    except httpx.ConnectError as e:
        raise NetworkError(f"Cannot connect to {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise AccessDeniedError(f"Access denied (403): {url}") from e
        if e.response.status_code == 404:
            raise InvalidURLError(f"URL not found (404): {url}") from e
        raise NetworkError(f"HTTP {e.response.status_code}: {e}") from e
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Typed fetch errors for granular API error handling
# ---------------------------------------------------------------------------

class FetchError(Exception):
    """Base class for fetch errors."""
    pass


class NetworkError(FetchError):
    """URL is unreachable or timed out."""
    pass


class NoTablesError(FetchError):
    """HTML was fetched but contains no <table> elements."""
    pass


class ParseError(FetchError):
    """HTML parsed but produced 0 eras or otherwise invalid data."""
    pass


class InvalidURLError(FetchError):
    """URL is malformed or not a valid tracker URL."""
    pass


class AccessDeniedError(FetchError):
    """Sheet is private, banned, or access-restricted (HTTP 403)."""
    pass


# ---------------------------------------------------------------------------
# Async variants
# ---------------------------------------------------------------------------

async def async_fetch_sheet_html(
    url: str,
    *,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    use_cache: bool = True,
) -> tuple[str, str]:
    """Async version of fetch_sheet_html — uses httpx.AsyncClient."""
    # Extract GID from original URL BEFORE normalization strips query/fragment
    if not gid:
        gid = _extract_gid_from_url(url)

    url = _normalize_url(url)

    # Check cache first (file I/O is fast enough sync)
    if use_cache and cache_ttl > 0:
        cached = _get_cached(url, cache_ttl)
        if cached is not None:
            return cached

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            if gid:
                sheet_url = _build_sheet_html_url(url, gid)
                r = await client.get(sheet_url)
                r.raise_for_status()
                title_match = TITLE_PATTERN.search(r.text)
                title = title_match.group(1) if title_match else ""
                if use_cache:
                    _set_cache(url, r.text, title)
                return r.text, title

            # Step 1: Fetch the base page
            r = await client.get(url)
            r.raise_for_status()
            base_html = r.text
            title_match = TITLE_PATTERN.search(base_html)
            title = title_match.group(1) if title_match else ""

            if "<table" in base_html.lower():
                if use_cache:
                    _set_cache(url, base_html, title)
                return base_html, title

            # Step 2: Discover GIDs
            gids = _discover_gids(base_html)
            if not gids:
                gids = ["0"]

            # Step 3: Try each GID
            last_error = None
            for try_gid in gids:
                try:
                    sheet_url = _build_sheet_html_url(url, try_gid)
                    r = await client.get(sheet_url)
                    if r.status_code == 200 and "<table" in r.text.lower():
                        if use_cache:
                            _set_cache(url, r.text, title)
                        return r.text, title
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    last_error = e
                    continue

            raise NoTablesError(
                f"No valid sheet data found at {url}. "
                f"Tried GIDs: {gids}. Last error: {last_error}"
            )

        except httpx.TimeoutException as e:
            raise NetworkError(f"Request timed out: {e}") from e
        except httpx.ConnectError as e:
            raise NetworkError(f"Cannot connect to {url}: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                raise AccessDeniedError(f"Access denied (403): {url}") from e
            if e.response.status_code == 404:
                raise InvalidURLError(f"URL not found (404): {url}") from e
            raise NetworkError(f"HTTP {e.response.status_code}: {e}") from e


async def _verify_art_images_async(
    artist: "Artist",
    art_map: dict[str, str],
    client: httpx.AsyncClient,
    threshold: int = 10,
) -> dict[str, str]:
    """Filter art_map to entries whose image is visually the same as the
    existing era.art_url, verified via perceptual hash (pHash).

    Entries with no existing era.art_url pass through unchanged (no baseline
    to compare against). On any download/decode/import error the entry also
    passes through (fail-open: never block upgrades on transient errors).

    Args:
        threshold: Maximum Hamming distance to consider images identical.
            Values 0–6 indicate the same image at different resolutions;
            16+ indicate different content. Default 10 provides a safe margin.
    """
    try:
        import io
        import imagehash
        from PIL import Image
    except ImportError:
        return art_map  # optional deps not installed — skip verification

    # Build {era_key: existing_url} for keys that appear in art_map
    existing_by_key: dict[str, str] = {}
    for era in artist.eras:
        if not era.art_url:
            continue
        key = _era_match_key(era.name)
        if key and key in art_map:
            existing_by_key[key] = era.art_url
        for alt in era.alt_names:
            ak = _era_match_key(alt)
            if ak and ak in art_map and ak not in existing_by_key:
                existing_by_key[ak] = era.art_url

    if not existing_by_key:
        return art_map  # no existing art to compare against

    def _phash(content: bytes) -> "imagehash.ImageHash":
        return imagehash.phash(Image.open(io.BytesIO(content)).convert("RGB"))

    async def _same_image(era_key: str, existing_url: str) -> tuple[str, bool]:
        try:
            r1, r2 = await asyncio.gather(
                client.get(existing_url, timeout=15),
                client.get(art_map[era_key], timeout=15),
            )
            if r1.status_code != 200 or r2.status_code != 200:
                return era_key, True  # can't fetch — pass through
            h1, h2 = await asyncio.gather(
                asyncio.to_thread(_phash, r1.content),
                asyncio.to_thread(_phash, r2.content),
            )
            return era_key, (h1 - h2) <= threshold
        except Exception:
            return era_key, True  # fail-open on any error

    results = await asyncio.gather(*[
        _same_image(k, v) for k, v in existing_by_key.items()
    ])

    filtered = dict(art_map)
    for era_key, is_same in results:
        if not is_same:
            filtered.pop(era_key, None)
    return filtered


async def async_fetch_and_parse(
    url: str,
    *,
    artist_name: str | None = None,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    use_cache: bool = True,
) -> Artist:
    """Async version of fetch_and_parse.

    Like the sync version, tries multiple GIDs when the first result
    produces 0 eras (handles landing-page sheets).
    """
    # Extract GID from original URL BEFORE normalization strips query/fragment
    if not gid:
        gid = _extract_gid_from_url(url)
    url_norm = _normalize_url(url)

    # Check parsed result cache first (skip entire parse pipeline)
    if use_cache and cache_ttl > 0:
        cached_artist = _get_cached_parsed(url_norm, cache_ttl)
        if cached_artist is not None:
            cached_artist.source_url = url
            return cached_artist

    # If a specific GID was requested, try it first.
    # If it produces 0 eras, fall through to GID discovery.
    if gid:
        try:
            html, title = await async_fetch_sheet_html(
                url, gid=gid, timeout=timeout, cache_ttl=cache_ttl, use_cache=use_cache
            )
            name = _resolve_artist_name(html, title, artist_name)
            artist = await asyncio.to_thread(parse_sheet, html, name)
            if artist.eras:
                # Before returning, check if this page reveals a better
                # "Unreleased" tab (e.g. Travis Scott's "Recents" landing tab).
                # The GID-specific HTML embeds all tab names via items.push() JS,
                # so no extra request is needed.
                named_tabs = _discover_named_tabs(html)
                unreleased_tab_gid = _get_unreleased_tab_gid(named_tabs)
                if not unreleased_tab_gid or unreleased_tab_gid == gid:
                    artist.source_url = url
                    if use_cache:
                        _set_cached_parsed(url_norm, artist)
                    return artist
                # A better "Unreleased" tab exists — fall through to full discovery
            # GID produced 0 eras — fall through to GID discovery below
        except (FetchError, httpx.HTTPError, ValueError):
            pass  # GID failed — fall through to GID discovery

    # Discover all GIDs and try them
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            r = await client.get(url_norm)
            r.raise_for_status()
            base_html = r.text
            title_match = TITLE_PATTERN.search(base_html)
            title = title_match.group(1) if title_match else ""

            # If base page has tables, try parsing directly
            if "<table" in base_html.lower():
                name = _resolve_artist_name(base_html, title, artist_name)
                artist = await asyncio.to_thread(parse_sheet, base_html, name)
                if artist.eras:
                    artist.source_url = url
                    if use_cache:
                        _set_cache(url_norm, base_html, title)
                    return artist

            gids = _discover_gids(base_html)
            if not gids:
                gids = ["0"]

            # Prioritize the "Unreleased" tab and identify Art tab GID
            gids, art_gid, unreleased_gid = _prioritize_gids(base_html, gids)

            # --- Fetch all GID pages concurrently, then parse to pick best ---
            async def _fetch_gid(gid_val: str) -> tuple[str, str] | None:
                """Fetch a single GID sheet page. Returns (gid, html) or None."""
                try:
                    sheet_url = _build_sheet_html_url(url_norm, gid_val)
                    if use_cache and cache_ttl > 0:
                        cached = _get_cached(sheet_url, cache_ttl)
                        if cached is not None:
                            return (gid_val, cached[0])
                        resp = await client.get(sheet_url)
                        if resp.status_code != 200 or "<table" not in resp.text.lower():
                            return None
                        if use_cache:
                            _set_cache(sheet_url, resp.text, title)
                        return (gid_val, resp.text)
                    else:
                        resp = await client.get(sheet_url)
                        if resp.status_code != 200 or "<table" not in resp.text.lower():
                            return None
                        return (gid_val, resp.text)
                except (httpx.HTTPError, ValueError, KeyError):
                    return None

            fetched = await asyncio.gather(*[_fetch_gid(g) for g in gids])

            best_artist: Artist | None = None
            best_eras = 0
            best_html = ""

            for result in fetched:
                if result is None:
                    continue
                result_gid, sheet_html = result
                try:
                    name = _resolve_artist_name(sheet_html, title, artist_name)
                    candidate = await asyncio.to_thread(parse_sheet, sheet_html, name)
                    n_eras = len(candidate.eras)
                    n_songs = sum(
                        len(s.songs)
                        for era in candidate.eras
                        for s in era.sections
                    )

                    logger.debug("GID %s → %d eras, %d songs", result_gid, n_eras, n_songs)
                    if n_eras > best_eras or (n_eras == best_eras and n_songs > 0):
                        best_eras = n_eras
                        best_artist = candidate
                        best_html = sheet_html

                    # Unreleased tab wins as long as it has at least 1 era —
                    # prevents Recents/landing tabs from outcompeting it on era count.
                    if result_gid == unreleased_gid and n_eras >= 1:
                        logger.debug("Selected unreleased GID %s (%d eras)", result_gid, n_eras)
                        break
                    elif n_eras >= _MIN_ERAS_FOR_VALID_GID:
                        break
                except (ValueError, KeyError):
                    continue

            if best_artist and best_eras > 0:
                best_artist.source_url = url
                # Fetch Art tab concurrently and upgrade era.art_url
                if art_gid:
                    try:
                        art_result = await _fetch_gid(art_gid)
                        if art_result:
                            _, art_html = art_result
                            art_map = await asyncio.to_thread(parse_art_tab, art_html)
                            if art_map:
                                art_map = await _verify_art_images_async(
                                    best_artist, art_map, client
                                )
                                if art_map:
                                    apply_art_tab_images(best_artist, art_map)
                    except Exception:
                        pass  # Art tab optional — keep existing art_url on failure
                if use_cache and best_html:
                    _set_cache(url_norm, best_html, title)
                _set_cached_parsed(url_norm, best_artist)
                return best_artist

            # Fallback
            html, title = await async_fetch_sheet_html(
                url, timeout=timeout, cache_ttl=cache_ttl, use_cache=use_cache
            )
            name = _resolve_artist_name(html, title, artist_name)
            artist = await asyncio.to_thread(parse_sheet, html, name)
            artist.source_url = url
            _set_cached_parsed(url_norm, artist)
            return artist

        except httpx.TimeoutException as e:
            raise NetworkError(f"Request timed out: {e}") from e
        except httpx.ConnectError as e:
            raise NetworkError(f"Cannot connect to {url}: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                raise AccessDeniedError(f"Access denied (403): {url}") from e
            if e.response.status_code == 404:
                raise InvalidURLError(f"URL not found (404): {url}") from e
            raise NetworkError(f"HTTP {e.response.status_code}: {e}") from e
