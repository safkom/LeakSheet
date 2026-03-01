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

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlencode

import httpx

from src.models import Artist
from src.parser import parse_sheet


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 60.0  # Large trackers (Ye: 10MB) need time
DEFAULT_CACHE_TTL = 3600  # 1 hour default cache
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LeakSheet/1.0"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

# Regex to extract sheet GIDs from the htmlview page JS
GID_PATTERN = re.compile(r"gid[=:]\s*[\"']?(\d+)")

# Regex to extract spreadsheet ID from Google Sheets URLs
SHEET_ID_PATTERN = re.compile(
    r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)"
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
        except (json.JSONDecodeError, OSError):
            pass
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

    def _resolve_artist_name(html: str, title: str) -> str:
        name = artist_name
        if not name:
            name = _infer_artist_name(title)
            sheet_artist = _infer_artist_from_sheet(html)
            if sheet_artist and sheet_artist.lower() != name.lower():
                name = sheet_artist
        return name

    # If a specific GID was requested, fetch just that one
    if gid:
        html, title = fetch_sheet_html(url, gid=gid, timeout=timeout,
                                        cache_ttl=cache_ttl, use_cache=use_cache)
        name = _resolve_artist_name(html, title)
        artist = parse_sheet(html, name)
        artist.source_url = url
        return artist

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
            name = _resolve_artist_name(base_html, title)
            artist = parse_sheet(base_html, name)
            if artist.eras:
                artist.source_url = url
                if use_cache:
                    _set_cache(url_norm, base_html, title)
                return artist

        # Step 2: Discover GIDs
        gids = _discover_gids(base_html)
        if not gids:
            gids = ["0"]

        # Step 3: Try each GID, pick the one that produces the most eras
        best_artist: Artist | None = None
        best_eras = 0
        best_html = ""

        for try_gid in gids:
            try:
                sheet_url = _build_sheet_html_url(url_norm, try_gid)

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

                name = _resolve_artist_name(sheet_html, title)
                candidate = parse_sheet(sheet_html, name)

                n_eras = len(candidate.eras)
                n_songs = sum(
                    len(section.songs)
                    for era in candidate.eras
                    for section in era.sections
                )

                if n_eras > best_eras or (n_eras == best_eras and n_songs > 0):
                    best_eras = n_eras
                    best_artist = candidate
                    best_html = sheet_html

                # If we found a good result (>5 eras), stop trying
                if n_eras >= 5:
                    break

            except (httpx.HTTPError, ValueError, KeyError):
                continue

        if best_artist and best_eras > 0:
            best_artist.source_url = url
            # Cache the best result under the original URL
            if use_cache and best_html:
                _set_cache(url_norm, best_html, title)
            return best_artist

        # Nothing worked — return whatever the first GID gave us
        html, title = fetch_sheet_html(url, timeout=timeout,
                                        cache_ttl=cache_ttl, use_cache=use_cache)
        name = _resolve_artist_name(html, title)
        artist = parse_sheet(html, name)
        artist.source_url = url
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

    def _resolve_name(html: str, title: str) -> str:
        name = artist_name
        if not name:
            name = _infer_artist_name(title)
            sheet_artist = _infer_artist_from_sheet(html)
            if sheet_artist and sheet_artist.lower() != name.lower():
                name = sheet_artist
        return name

    # If a specific GID was requested, fetch just that one
    if gid:
        html, title = await async_fetch_sheet_html(
            url, gid=gid, timeout=timeout, cache_ttl=cache_ttl, use_cache=use_cache
        )
        name = _resolve_name(html, title)
        artist = parse_sheet(html, name)
        artist.source_url = url
        return artist

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
                name = _resolve_name(base_html, title)
                artist = parse_sheet(base_html, name)
                if artist.eras:
                    artist.source_url = url
                    if use_cache:
                        _set_cache(url_norm, base_html, title)
                    return artist

            gids = _discover_gids(base_html)
            if not gids:
                gids = ["0"]

            best_artist: Artist | None = None
            best_eras = 0
            best_html = ""

            for try_gid in gids:
                try:
                    sheet_url = _build_sheet_html_url(url_norm, try_gid)

                    if use_cache and cache_ttl > 0:
                        cached = _get_cached(sheet_url, cache_ttl)
                        if cached is not None:
                            sheet_html, _ = cached
                        else:
                            resp = await client.get(sheet_url)
                            if resp.status_code != 200 or "<table" not in resp.text.lower():
                                continue
                            sheet_html = resp.text
                            if use_cache:
                                _set_cache(sheet_url, sheet_html, title)
                    else:
                        resp = await client.get(sheet_url)
                        if resp.status_code != 200 or "<table" not in resp.text.lower():
                            continue
                        sheet_html = resp.text

                    name = _resolve_name(sheet_html, title)
                    candidate = parse_sheet(sheet_html, name)
                    n_eras = len(candidate.eras)
                    n_songs = sum(
                        len(s.songs)
                        for era in candidate.eras
                        for s in era.sections
                    )

                    if n_eras > best_eras or (n_eras == best_eras and n_songs > 0):
                        best_eras = n_eras
                        best_artist = candidate
                        best_html = sheet_html

                    if n_eras >= 5:
                        break

                except (httpx.HTTPError, ValueError, KeyError):
                    continue

            if best_artist and best_eras > 0:
                best_artist.source_url = url
                if use_cache and best_html:
                    _set_cache(url_norm, best_html, title)
                return best_artist

            # Fallback
            html, title = await async_fetch_sheet_html(
                url, timeout=timeout, cache_ttl=cache_ttl, use_cache=use_cache
            )
            name = _resolve_name(html, title)
            artist = parse_sheet(html, name)
            artist.source_url = url
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
