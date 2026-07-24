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
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse, urlencode

import httpx

logger = logging.getLogger(__name__)

from src.config import USER_AGENT
from src.models import Artist, TabSection
from src.parser import (
    apply_art_tab_images,
    apply_badge_tabs,
    parse_art_tab,
    parse_misc_tab,
    parse_sheet,
    _era_match_key,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 60.0  # Large trackers (Ye: 10MB) need time
DEFAULT_CACHE_TTL = 3600  # 1 hour default cache
STALE_CACHE_TTL = 86400  # 24h max age for stale-while-revalidate
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

# Size cap for the sheet HTML + parsed-JSON cache (2026-07-20 review: the
# image cache has had a 200MB cap for a while, the sheet cache had none — a
# TrackerHub sweep left ~700MB behind on a 512MB-class box). Oldest entries
# (grouped per hash stem) are evicted first; img_* files have their own cap.
_SHEET_CACHE_MAX_BYTES = int(
    os.environ.get("LEAKSHEET_SHEET_CACHE_MAX_BYTES", str(1024 * 1024 * 1024))
)
_SHEET_EVICT_MIN_INTERVAL = 60.0  # scan the dir at most once a minute
_last_sheet_evict = 0.0


class PhaseTimer:
    """Collects per-phase wall-clock durations across one request.

    Phases repeat (e.g. one ``gid_fetch`` per tab) and accumulate. Exposed to
    clients via the ``Server-Timing`` response header so slow requests can be
    diagnosed from curl or the app without server log access.
    """

    def __init__(self) -> None:
        self.phases: dict[str, float] = {}

    @contextmanager
    def phase(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = self.phases.get(name, 0.0) + time.perf_counter() - start

    def server_timing_header(self) -> str:
        return ", ".join(
            f"{name};dur={dur * 1000:.1f}" for name, dur in self.phases.items()
        )

    def log_line(self) -> str:
        total = sum(self.phases.values())
        parts = " ".join(f"{n}={d * 1000:.0f}ms" for n, d in self.phases.items())
        return f"{parts} total={total * 1000:.0f}ms"

# ---------------------------------------------------------------------------
# Shared async HTTP client (connection-pooled, reused across requests)
# ---------------------------------------------------------------------------

_sheets_client: httpx.AsyncClient | None = None


def _get_sheets_client() -> httpx.AsyncClient:
    """Return (or lazily create) the module-level shared httpx.AsyncClient."""
    global _sheets_client
    if _sheets_client is None or _sheets_client.is_closed:
        _sheets_client = httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    return _sheets_client


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

# Secondary content tabs parsed into Artist.misc_entries. Keys are cleaned
# tab names (emoji stripped, lowercased); values are the source_tab kind.
_MISC_TAB_NAMES = frozenset({"misc", "misc.", "miscellaneous"})
_MUSIC_VIDEO_TAB_NAMES = frozenset({"music videos", "music video", "videos", "mvs"})

# Extra content tabs parsed into Artist.tabs (2026-07-17, from a live tab
# census of the Ye / Travis / Kendrick / Carti trackers). Released tabs use
# the Misc-tab grammar; Best Of / Worst Of / Stems and the "other" set use
# the Unreleased-tab grammar — both parse via parse_misc_tab's alias table.
_RELEASED_TAB_NAMES = frozenset({"released"})
_BEST_OF_TAB_NAMES = frozenset({"best of"})
_WORST_OF_TAB_NAMES = frozenset({"worst of"})
_STEMS_TAB_NAMES = frozenset({"stems"})
_SPECIAL_TAB_NAMES = frozenset({"special", "notable"})
# Slash spacing is normalized to " / " by _clean_tab_name before matching;
# "grails & wanted" observed 7x in the 2026-07-20 TrackerHub sweep.
_GRAILS_TAB_NAMES = frozenset({"grails", "grails / wanted", "grails & wanted"})
_WANTED_TAB_NAMES = frozenset({"wanted"})
_FAKES_TAB_NAMES = frozenset({"fakes"})

# Content-bearing tabs without a dedicated kind — parsed generically and
# exposed with kind="other" plus the tab's display name.
_OTHER_CONTENT_TAB_NAMES = frozenset({
    "live performances", "performances",
    "ai tracks", "remixes", "edits (wip)", "edits/remasters", "edits / remasters",
})

# Tab kinds whose entries duplicate main-tab songs with a highlight (⭐/🗑/✨/
# 🏆/🥇). These never become switchable pages — their entries are matched
# against the era tree and stamp the corresponding badge on existing songs,
# covering trackers that only mark highlights in the dedicated tab.
_BADGE_TAB_KINDS = frozenset({"best_of", "worst_of", "special", "grails", "wanted"})

# Deliberately NOT parsed (census 2026-07-17): "recent" duplicates the main
# tab; tracklists / album copies / groupbuys / buys / compilations / tours /
# samples / og files (wip) / og snippets have bespoke non-song grammars; key /
# socials / bpm & keys are lookup tables.

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

# Common title suffixes to strip when inferring artist name. Compared
# case-insensitively — yetracker.net titles itself " - Google disk" (sic).
TITLE_SUFFIXES = [
    " - Google Drive",
    " - Google Disk",
    " - Google Sheets",
    " - Google Docs",
    " Music Tracker",
    " Tracker [Currently in Use]",
    " Tracker",
    " Leak Tracker",
    " Leaks Tracker",
]

# Emoji pattern for stripping decorative emoji from tab names.
# Ranges include Enclosed Alphanumeric Supplement (\ud83c\udd95 U+1F195) and
# Miscellaneous Technical (\u23ed U+23ED) \u2014 both appear in real tab names.
_EMOJI_RE = re.compile(
    r"[\U0001f170-\U0001f9ff\U00002300-\U000023ff\U00002600-\U000027bf\U00002b50\ufe0f\u200d]+"
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
    else:
        # Non-Google hosts (yetracker.net): 'host' and 'host/' are the same
        # resource but hash to different cache keys — canonicalize the bare
        # host-root form to a trailing slash.
        parsed = urlparse(url)
        if not parsed.path and not parsed.query and not parsed.fragment:
            url = url + "/"

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

    # Step 1: Strip known suffixes (" - Google Drive", " Tracker", etc.),
    # case-insensitively.
    for suffix in TITLE_SUFFIXES:
        if name.lower().endswith(suffix.lower()):
            name = name[: -len(suffix)].strip()

    # Step 1b: Strip "Tracker 2.0" / "Tracker v3" version suffixes and
    # "Tracker PUBLIC" / "Tracker [Official]" style qualifiers that follow
    # the word Tracker (2026-07-06 census: 'Ye Tracker PUBLIC',
    # 'Playboi Carti Tracker [Official]')
    name = re.sub(
        r"\s+Tracker\s+(?:[\d.v]+|PUBLIC|PRIVATE|OFFICIAL|UNOFFICIAL|BACKUP|ARCHIVE|\[[^\]]*\]|\([^)]*\))\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    # Re-apply suffix stripping after version removal
    for suffix in TITLE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()

    # Step 2: Strip trailing parenthetical/bracketed metadata like
    # "(reup 12.29.25)" or "[Official]" that prevents suffix stripping
    paren_match = re.search(r"\s*[\(\[][^)\]]*[\)\]]\s*$", name)
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
        # Some trackers flip the comma order as a joke.
        "creator, the tyler": "Tyler, The Creator",
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


_JS_ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\.")


def _decode_js_string(s: str) -> str:
    """Decode JS string-literal escapes in captured tab names.

    Real tab names arrive escaped inside the htmlview JS: "Grails \\/ Wanted",
    "BPM \\x26 Keys" (\\x26 == "&"), emoji as \\uD83C\\uDFC6 surrogate pairs.
    Without decoding, these names never match any keyword set.
    """

    def _sub(m: re.Match) -> str:
        esc = m.group(0)
        if esc.startswith("\\u") or esc.startswith("\\x"):
            return chr(int(esc[2:], 16))
        return esc[1]  # \/ \u2192 /, \\ \u2192 \, \" \u2192 "

    decoded = _JS_ESCAPE_RE.sub(_sub, s)
    # Recombine UTF-16 surrogate pairs produced by \ud83c\udfc6-style emoji. A lone
    # (truncated) surrogate can't round-trip \u2014 keep the raw string rather
    # than aborting tab discovery for the whole tracker.
    try:
        return decoded.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeDecodeError:
        return "".join(c for c in decoded if not 0xD800 <= ord(c) <= 0xDFFF)


def _discover_named_tabs(html: str) -> dict[str, str]:
    """Extract {gid: tab_name} mapping from htmlview page HTML/JS.

    Google Sheets htmlview embeds tab metadata as JS items.push() calls:
      items.push({name: "Art", pageUrl: "...", gid: "1234", ...});
    Tab names may contain leading emoji (e.g. "\U0001f5bc\ufe0f Art") and
    JS string escapes, which are decoded before use.
    """
    result: dict[str, str] = {}
    for name, gid in _TAB_ITEMS_PATTERN.findall(html):
        name = _decode_js_string(name).strip()
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


def _clean_tab_name(name: str) -> str:
    """Normalize a sheet tab name for keyword matching (strip emoji, lower).

    2026-07-20 sweep: also strips trailing parenthetical/bracket qualifiers —
    '(WIP)'-suffixed content tabs ('Released (WIP)', 'Stems [WIP]', 'Art
    (wip)') appeared 60+ times across TrackerHub and fell out of
    classification entirely — and normalizes slash spacing so 'Grails/
    Wanted' matches the 'grails / wanted' keyword set.
    """
    clean = _EMOJI_RE.sub(" ", name).strip().lower()
    clean = re.sub(r"[\(\[][^)\]]*[\)\]]\s*$", "", clean).strip()
    clean = re.sub(r"\s*/\s*", " / ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _get_art_tab_gid(named_tabs: dict[str, str]) -> str | None:
    """Return the GID of the Art tab if one is present, else None.

    Strips emoji and normalises whitespace before comparing against the
    known art-tab keyword set ({"art", "album art", "cover art", ...}).
    """
    for gid, name in named_tabs.items():
        if _clean_tab_name(name) in _ART_TAB_NAMES:
            return gid
    return None


# Kind resolution order for content tabs; earlier entries sort first in the
# API's tabs list (misc keeps its historical first position).
_CONTENT_TAB_KINDS: list[tuple[frozenset, str]] = [
    (_MISC_TAB_NAMES, "misc"),
    (_MUSIC_VIDEO_TAB_NAMES, "music_videos"),
    (_RELEASED_TAB_NAMES, "released"),
    (_BEST_OF_TAB_NAMES, "best_of"),
    (_WORST_OF_TAB_NAMES, "worst_of"),
    (_SPECIAL_TAB_NAMES, "special"),
    (_GRAILS_TAB_NAMES, "grails"),
    (_WANTED_TAB_NAMES, "wanted"),
    (_STEMS_TAB_NAMES, "stems"),
    (_FAKES_TAB_NAMES, "fakes"),
    (_OTHER_CONTENT_TAB_NAMES, "other"),
]


def _get_content_tabs(named_tabs: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return [(gid, kind, display_name)] for every parseable content tab.

    Tabs not in any keyword set — the main tracker, Art, and the
    deliberately-excluded non-song tabs — are omitted. Sorted by kind
    resolution order (misc first), then by gid for stability.
    """
    order = {kind: i for i, (_, kind) in enumerate(_CONTENT_TAB_KINDS)}
    tabs: list[tuple[str, str, str]] = []
    for gid, name in named_tabs.items():
        clean = _clean_tab_name(name)
        for names, kind in _CONTENT_TAB_KINDS:
            if clean in names:
                tabs.append((gid, kind, name))
                break
    tabs.sort(key=lambda t: (order[t[1]], t[0]))
    return tabs


# ---------------------------------------------------------------------------
# File-based cache
# ---------------------------------------------------------------------------


def compute_content_hash(data: dict) -> str:
    """Compute a short SHA-256 hash of serialized data as content fingerprint (ETag)."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


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


def _evict_sheet_cache() -> None:
    """Drop the oldest sheet-cache entries once the cache exceeds the cap.

    Entries are grouped per hash stem (.html / .meta.json / .parsed.json
    evicted together, so no orphan meta or parsed files survive) and ranked
    by their most recent mtime. ``img_*`` files belong to the image cache,
    which has its own cap — never touched here.
    """
    if not CACHE_DIR.exists():
        return
    groups: dict[str, list[tuple[float, int, Path]]] = {}
    total = 0
    for path in CACHE_DIR.iterdir():
        if not path.is_file() or path.name.startswith("img_"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        stem = path.name.split(".", 1)[0]
        groups.setdefault(stem, []).append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size
    if total <= _SHEET_CACHE_MAX_BYTES:
        return
    ranked = sorted(
        groups.values(), key=lambda files: max(m for m, _, _ in files)
    )
    for files in ranked:
        if total <= _SHEET_CACHE_MAX_BYTES:
            break
        for _, size, victim in files:
            total -= size
            try:
                victim.unlink()
            except OSError:
                pass


def _maybe_evict_sheet_cache() -> None:
    """Throttled eviction — a full dir scan at most every minute."""
    global _last_sheet_evict
    now = time.time()
    if now - _last_sheet_evict < _SHEET_EVICT_MIN_INTERVAL:
        return
    _last_sheet_evict = now
    try:
        _evict_sheet_cache()
    except OSError as e:
        logger.warning("Sheet-cache eviction failed: %s", e)


def _set_cache(url: str, html: str, title: str) -> None:
    """Write HTML and metadata to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url)
    (CACHE_DIR / f"{key}.html").write_text(html, encoding="utf-8")
    (CACHE_DIR / f"{key}.meta.json").write_text(
        json.dumps({"url": url, "title": title, "timestamp": time.time()}),
        encoding="utf-8",
    )
    _maybe_evict_sheet_cache()


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
                return Artist.model_validate(data)
        except Exception as e:
            # Any unreadable/invalid cache entry (corrupt JSON, IO error,
            # pydantic schema drift after a model change) is a cache miss —
            # never let cache corruption break a request.
            logger.warning("Parsed cache read failed for %s: %s", url[:80], e)
    return None


def _set_cached_parsed(url: str, artist: Artist) -> None:
    """Write parsed Artist JSON to cache, with content hash in metadata."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url)
    try:
        data = artist.model_dump()
        (CACHE_DIR / f"{key}.parsed.json").write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
        # Update metadata with content hash for ETag support
        meta_file = CACHE_DIR / f"{key}.meta.json"
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        meta["content_hash"] = compute_content_hash(data)
        meta_file.write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        _maybe_evict_sheet_cache()
    except (OSError, TypeError) as e:
        logger.warning("Failed to cache parsed result: %s", e)


async def _async_get_cached(url: str, cache_ttl: float = DEFAULT_CACHE_TTL) -> tuple[str, str] | None:
    return await asyncio.to_thread(_get_cached, url, cache_ttl)


async def _async_set_cache(url: str, html: str, title: str) -> None:
    await asyncio.to_thread(_set_cache, url, html, title)


async def _async_get_cached_parsed(url: str, cache_ttl: float = DEFAULT_CACHE_TTL) -> "Artist | None":
    return await asyncio.to_thread(_get_cached_parsed, url, cache_ttl)


async def _async_set_cached_parsed(url: str, artist: "Artist") -> None:
    await asyncio.to_thread(_set_cached_parsed, url, artist)


def stale_parsed_cache_urls(limit: int) -> list[str]:
    """URLs of cached parses inside the stale-while-revalidate gap.

    These are trackers someone actually uses (they have a parsed cache entry)
    whose next request would be served stale (age between DEFAULT_CACHE_TTL
    and STALE_CACHE_TTL). The prewarm loop refreshes them in the background
    so frequently-updated trackers serve fresh data instead of stale-first.
    Freshest-stale first — those are the most likely to be requested again —
    capped at ``limit`` per call.
    """
    if not CACHE_DIR.exists():
        return []
    now = time.time()
    candidates: list[tuple[float, str]] = []
    for meta_file in CACHE_DIR.glob("*.meta.json"):
        stem = meta_file.name.removesuffix(".meta.json")
        if not (CACHE_DIR / f"{stem}.parsed.json").exists():
            continue  # gid sub-pages etc. — only full parses are prewarmed
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        url = meta.get("url")
        ts = meta.get("timestamp", 0)
        if not url or ts <= 0:
            continue
        age = now - ts
        if DEFAULT_CACHE_TTL < age <= STALE_CACHE_TTL:
            candidates.append((age, url))
    candidates.sort()
    return [url for _, url in candidates[:limit]]


def clear_cache() -> int:
    """Remove all cached files (sheet HTML/parsed JSON and resized images).

    Returns number of files deleted.
    """
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.iterdir():
        if f.is_file():
            f.unlink()
            count += 1
    return count


# ---------------------------------------------------------------------------
# Public cache info helpers (used by API layer for ETag / stale-while-revalidate)
# ---------------------------------------------------------------------------

def get_cached_etag(url: str) -> str | None:
    """Return the content hash (ETag) for a cached parsed result, or None."""
    url_norm = _normalize_url(url)
    key = _cache_key(url_norm)
    meta_file = CACHE_DIR / f"{key}.meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            return meta.get("content_hash")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def get_cached_age(url: str) -> float | None:
    """Return seconds since the URL was last fetched, or None if not cached."""
    url_norm = _normalize_url(url)
    key = _cache_key(url_norm)
    meta_file = CACHE_DIR / f"{key}.meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            ts = meta.get("timestamp", 0)
            if ts > 0:
                return time.time() - ts
        except (json.JSONDecodeError, OSError):
            pass
    return None


def get_cached_parsed_bytes(
    url: str, max_age: float = STALE_CACHE_TTL
) -> tuple[bytes, str | None, float] | None:
    """Return (raw parsed-cache JSON bytes, stored content hash, age seconds)
    for a cache entry within ``max_age``, or None.

    Serving the raw file bytes skips pydantic validation and re-serialization
    of multi-MB artists on the warm path. The stored content hash equals the
    ETag the full path would compute for the same data (both derive from the
    identical ``artist.dict()`` written at cache time).
    """
    url_norm = _normalize_url(url)
    key = _cache_key(url_norm)
    parsed_file = CACHE_DIR / f"{key}.parsed.json"
    meta_file = CACHE_DIR / f"{key}.meta.json"
    if not parsed_file.exists() or not meta_file.exists():
        return None
    try:
        meta = json.loads(meta_file.read_text())
        ts = meta.get("timestamp", 0)
        if ts <= 0:
            return None
        age = time.time() - ts
        if age > max_age:
            return None
        return parsed_file.read_bytes(), meta.get("content_hash"), age
    except (OSError, json.JSONDecodeError):
        return None


async def async_get_cached_parsed_bytes(
    url: str, max_age: float = STALE_CACHE_TTL
) -> tuple[bytes, str | None, float] | None:
    """Async variant of get_cached_parsed_bytes."""
    return await asyncio.to_thread(get_cached_parsed_bytes, url, max_age)


async def async_get_cached_etag(url: str) -> str | None:
    """Async variant of get_cached_etag."""
    return await asyncio.to_thread(get_cached_etag, url)


async def async_get_cached_age(url: str) -> float | None:
    """Async variant of get_cached_age."""
    return await asyncio.to_thread(get_cached_age, url)


# ---------------------------------------------------------------------------
# Shared parse helpers
# ---------------------------------------------------------------------------

def _resolve_artist_name(title: str, artist_name_override: str | None) -> str:
    """Determine the artist name, with an optional caller override.

    Priority:
    1. ``artist_name_override`` if provided.
    2. Name inferred from the page ``<title>`` after stripping common
       suffixes/prefixes (see ``_infer_artist_name``).
    """
    if artist_name_override:
        return artist_name_override
    return _infer_artist_name(title)


def _prioritize_gids(
    base_html: str, gids: list[str]
) -> tuple[list[str], str | None, str | None, list[tuple[str, str, str]]]:
    """Reorder GIDs so the main tracker tab is tried first.

    Returns (reordered_gids, art_gid, unreleased_gid, content_tabs) where
    content_tabs is [(gid, kind, display_name)] for every parseable
    secondary tab (misc, music_videos, released, best_of, worst_of, stems,
    other). Moves the identified "Unreleased" tab GID to the front when
    found, so trackers with a landing/recent tab (e.g. Travis Scott 2.0)
    don't get stuck on the wrong sheet. Art and content tabs are removed
    from the candidate list — they are secondary content, never the main
    tracker, and fetching them as candidates wastes bandwidth.
    """
    named_tabs = _discover_named_tabs(base_html)
    art_gid = _get_art_tab_gid(named_tabs)
    unreleased_gid = _get_unreleased_tab_gid(named_tabs)
    content_tabs = _get_content_tabs(named_tabs)

    exclude = {gid for gid, _, _ in content_tabs}
    if art_gid:
        exclude.add(art_gid)
    filtered = [g for g in gids if g not in exclude]
    if filtered:
        gids = filtered

    if unreleased_gid and unreleased_gid in gids:
        logger.debug("Unreleased tab detected (gid=%s) — trying first", unreleased_gid)
        gids = [unreleased_gid] + [g for g in gids if g != unreleased_gid]
    return gids, art_gid, unreleased_gid, content_tabs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _run_sync(coro_factory):
    """Run an async-pipeline coroutine from synchronous code (CLI scripts).

    Creates a private event loop via ``asyncio.run`` and closes the shared
    AsyncClient inside that loop afterwards — the pooled client is loop-bound
    once used, so leaving it open would break the next sync call. Never call
    this from async code; use the ``async_*`` functions directly.
    """
    async def _runner():
        global _sheets_client
        try:
            return await coro_factory()
        finally:
            if _sheets_client is not None and not _sheets_client.is_closed:
                await _sheets_client.aclose()
            _sheets_client = None
    return asyncio.run(_runner())


def fetch_sheet_html(
    url: str,
    *,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    use_cache: bool = True,
) -> tuple[str, str]:
    """Synchronous wrapper around :func:`async_fetch_sheet_html` (CLI scripts)."""
    return _run_sync(lambda: async_fetch_sheet_html(
        url, gid=gid, timeout=timeout, cache_ttl=cache_ttl, use_cache=use_cache
    ))


def fetch_and_parse(
    url: str,
    *,
    artist_name: str | None = None,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    use_cache: bool = True,
    write_cache: bool | None = None,
) -> Artist:
    """Synchronous wrapper around :func:`async_fetch_and_parse` (CLI scripts).

    This used to be a separate ~340-line sync pipeline that had drifted from
    the async one (it ignored ``artist_name`` on one fallback branch and never
    fetched content tabs). Delegating guarantees parity.
    """
    return _run_sync(lambda: async_fetch_and_parse(
        url, artist_name=artist_name, gid=gid, timeout=timeout,
        cache_ttl=cache_ttl, use_cache=use_cache, write_cache=write_cache,
    ))


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


def _raise_fetch_error(exc: httpx.HTTPError, url: str) -> "NoReturn":
    """Map an httpx exception onto the typed FetchError hierarchy.

    Single source for the mapping both async entry points use — this block
    used to be copy-pasted per function and drifted between copies.
    """
    if isinstance(exc, httpx.TimeoutException):
        raise NetworkError(f"Request timed out: {exc}") from exc
    if isinstance(exc, httpx.ConnectError):
        raise NetworkError(f"Cannot connect to {url}: {exc}") from exc
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 403:
            raise AccessDeniedError(f"Access denied (403): {url}") from exc
        if code == 404:
            raise InvalidURLError(f"URL not found (404): {url}") from exc
        raise NetworkError(f"HTTP {code}: {exc}") from exc
    raise exc


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

    if use_cache and cache_ttl > 0:
        cached = await _async_get_cached(url, cache_ttl)
        if cached is not None:
            return cached

    client = _get_sheets_client()
    try:
        if gid:
            sheet_url = _build_sheet_html_url(url, gid)
            r = await client.get(sheet_url, timeout=timeout)
            r.raise_for_status()
            title_match = TITLE_PATTERN.search(r.text)
            title = title_match.group(1) if title_match else ""
            if use_cache:
                await _async_set_cache(url, r.text, title)
            return r.text, title

        # Step 1: Fetch the base page
        r = await client.get(url, timeout=timeout)
        r.raise_for_status()
        base_html = r.text
        title_match = TITLE_PATTERN.search(base_html)
        title = title_match.group(1) if title_match else ""

        if "<table" in base_html.lower():
            if use_cache:
                await _async_set_cache(url, base_html, title)
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
                r = await client.get(sheet_url, timeout=timeout)
                if r.status_code == 200 and "<table" in r.text.lower():
                    if use_cache:
                        await _async_set_cache(url, r.text, title)
                    return r.text, title
            except (httpx.HTTPError, ValueError, KeyError) as e:
                last_error = e
                continue

        raise NoTablesError(
            f"No valid sheet data found at {url}. "
            f"Tried GIDs: {gids}. Last error: {last_error}"
        )

    except httpx.HTTPError as e:
        _raise_fetch_error(e, url)


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


async def _fetch_gid_page(
    url_norm: str,
    gid_val: str,
    title: str,
    *,
    client: httpx.AsyncClient,
    timeout: float,
    cache_ttl: float,
    use_cache: bool,
    t: PhaseTimer,
) -> tuple[str, str] | None:
    """Fetch a single GID sheet page. Returns (gid, html) or None."""
    try:
        with t.phase("gid_fetch"):
            sheet_url = _build_sheet_html_url(url_norm, gid_val)
            if use_cache and cache_ttl > 0:
                cached = await _async_get_cached(sheet_url, cache_ttl)
                if cached is not None:
                    return (gid_val, cached[0])
            resp = await client.get(sheet_url, timeout=timeout)
            if resp.status_code != 200 or "<table" not in resp.text.lower():
                return None
            if use_cache and cache_ttl > 0:
                await _async_set_cache(sheet_url, resp.text, title)
            return (gid_val, resp.text)
    except (httpx.HTTPError, ValueError, KeyError):
        return None


async def _load_secondary_tabs(
    artist: Artist,
    art_gid: str | None,
    content_tabs: list[tuple[str, str, str]],
    url_norm: str,
    title: str,
    *,
    client: httpx.AsyncClient,
    timeout: float,
    cache_ttl: float,
    use_cache: bool,
    t: PhaseTimer,
) -> None:
    """Fetch + parse the Art tab and all content tabs into *artist*.

    Everything here is optional — a failure never fails the request. Called
    from both the explicit-GID fast path and the full-discovery path, so the
    returned content no longer depends on which URL shape the client used.
    Misc/MV entries stay in the flat ``misc_entries`` list for backward
    compatibility; every non-empty tab also lands in ``Artist.tabs``.
    """
    if not art_gid and not content_tabs:
        return

    async def _fetch(gid_val: str) -> tuple[str, str] | None:
        return await _fetch_gid_page(
            url_norm, gid_val, title,
            client=client, timeout=timeout, cache_ttl=cache_ttl,
            use_cache=use_cache, t=t,
        )

    async def _load_art() -> None:
        try:
            with t.phase("art_fetch"):
                art_result = await _fetch(art_gid)
            if art_result:
                _, art_html = art_result
                with t.phase("art_parse"):
                    art_map = await asyncio.to_thread(parse_art_tab, art_html)
                if art_map:
                    with t.phase("art_verify"):
                        art_map = await _verify_art_images_async(
                            artist, art_map, client
                        )
                    if art_map:
                        apply_art_tab_images(artist, art_map)
        except Exception as e:
            # Art tab optional — keep existing art_url on failure
            logger.debug("Art tab load failed for %s: %s", url_norm[:80], e)

    tab_results: dict[str, list] = {}

    async def _load_tab(gid_val: str, kind: str) -> None:
        try:
            with t.phase("misc_fetch"):
                result = await _fetch(gid_val)
            if result:
                _, tab_html = result
                with t.phase("misc_parse"):
                    tab_results[gid_val] = await asyncio.to_thread(
                        parse_misc_tab, tab_html, kind
                    )
        except Exception as e:
            # Content tabs optional
            logger.debug("Content tab %s load failed: %s", gid_val, e)

    secondary = [_load_tab(g, k) for g, k, _n in content_tabs]
    if art_gid:
        secondary.append(_load_art())
    if secondary:
        await asyncio.gather(*secondary)
    # Extend in declared tab order (misc first) for stable output.
    badge_tabs: list[tuple[str, list]] = []
    for gid_val, kind, display_name in content_tabs:
        entries = tab_results.get(gid_val, [])
        if not entries:
            continue
        if kind in ("misc", "music_videos"):
            artist.misc_entries.extend(entries)
        if kind in _BADGE_TAB_KINDS:
            # Highlight tabs annotate existing songs; they are not pages.
            badge_tabs.append((kind, entries))
            continue
        artist.tabs.append(
            TabSection(kind=kind, name=display_name, entries=entries)
        )
    if badge_tabs:
        # One O(songs) index build for all badge tabs, off the event loop.
        with t.phase("badge_annotate"):
            applied = await asyncio.to_thread(apply_badge_tabs, artist, badge_tabs)
        logger.debug(
            "Badge tabs %s: %d entries matched songs",
            [k for k, _ in badge_tabs], applied,
        )


async def async_fetch_and_parse(
    url: str,
    *,
    artist_name: str | None = None,
    gid: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    use_cache: bool = True,
    write_cache: bool | None = None,
    timer: PhaseTimer | None = None,
) -> Artist:
    """Async version of fetch_and_parse.

    Like the sync version, tries multiple GIDs when the first result
    produces 0 eras (handles landing-page sheets).

    ``use_cache`` gates cache *reads*; ``write_cache`` gates cache *writes*
    and defaults to ``use_cache`` when unset. A force-refresh passes
    ``use_cache=False`` (skip the stale copy) but ``write_cache=True`` so the
    fresh parse still populates the cache for the next reader — otherwise every
    request after a force-refresh pays a full cold fetch.
    """
    if write_cache is None:
        write_cache = use_cache
    t = timer if timer is not None else PhaseTimer()
    # Extract GID from original URL BEFORE normalization strips query/fragment
    if not gid:
        gid = _extract_gid_from_url(url)
    url_norm = _normalize_url(url)

    # Check parsed result cache first (skip entire parse pipeline)
    if use_cache and cache_ttl > 0:
        with t.phase("cache_read"):
            cached_artist = await _async_get_cached_parsed(url_norm, cache_ttl)
        if cached_artist is not None:
            cached_artist.source_url = url
            return cached_artist

    # If a specific GID was requested, try it first.
    # If it produces 0 eras, fall through to GID discovery.
    client = _get_sheets_client()
    if gid:
        try:
            with t.phase("gid_fetch"):
                html, title = await async_fetch_sheet_html(
                    url, gid=gid, timeout=timeout, cache_ttl=cache_ttl, use_cache=use_cache
                )
            # Per-GID sub-pages don't embed the workbook's tab listing (only
            # the base /htmlview page does), so a link straight to the
            # Misc/Music-Videos tab (e.g. copied from the browser while
            # viewing it) can only be told apart from the main tab by asking
            # the base page. This matters because parse_sheet's Era/Name/
            # Available/Quality columns are similar enough to the misc-tab
            # grammar that it can extract a plausible-looking but wrong
            # "eras" list from that tab, which would then short-circuit
            # discovery of the real main tab and skip parsing this tab as
            # misc entries entirely.
            named_tabs: dict[str, str] = {}
            try:
                with t.phase("base_fetch"):
                    base_resp = await client.get(url_norm, timeout=timeout)
                    base_resp.raise_for_status()
                named_tabs = _discover_named_tabs(base_resp.text)
            except httpx.HTTPError:
                pass  # Can't tell — fall back to trusting parse_sheet below
            gid_is_misc_tab = gid in {g for g, _kind, _n in _get_content_tabs(named_tabs)}
            if not gid_is_misc_tab:
                name = _resolve_artist_name(title, artist_name)
                with t.phase("parse"):
                    artist = await asyncio.to_thread(parse_sheet, html, name)
                if artist.eras:
                    # Before returning, check if this page reveals a better
                    # "Unreleased" tab (e.g. Travis Scott's "Recents" landing tab).
                    unreleased_tab_gid = _get_unreleased_tab_gid(named_tabs)
                    if not unreleased_tab_gid or unreleased_tab_gid == gid:
                        artist.source_url = url
                        # Load Art + content tabs here too — without this,
                        # a URL carrying the main tab's gid returned less
                        # content than the same tracker via discovery.
                        await _load_secondary_tabs(
                            artist,
                            _get_art_tab_gid(named_tabs),
                            _get_content_tabs(named_tabs),
                            url_norm, title,
                            client=client, timeout=timeout,
                            cache_ttl=cache_ttl, use_cache=use_cache, t=t,
                        )
                        if write_cache:
                            await _async_set_cached_parsed(url_norm, artist)
                        return artist
                    # A better "Unreleased" tab exists — fall through to full discovery
                # GID produced 0 eras — fall through to GID discovery below
            # else: gid is the Misc/Music-Videos tab itself — skip straight to
            # full discovery below, which finds the real main tab and parses
            # this tab correctly via parse_misc_tab.
        except (FetchError, httpx.HTTPError, ValueError):
            pass  # GID failed — fall through to GID discovery

    # Discover all GIDs and try them
    try:
        with t.phase("base_fetch"):
            r = await client.get(url_norm, timeout=timeout)
            r.raise_for_status()
            base_html = r.text
        title_match = TITLE_PATTERN.search(base_html)
        title = title_match.group(1) if title_match else ""

        # If base page has tables, try parsing directly
        if "<table" in base_html.lower():
            name = _resolve_artist_name(title, artist_name)
            with t.phase("parse"):
                artist = await asyncio.to_thread(parse_sheet, base_html, name)
            if artist.eras:
                artist.source_url = url
                if write_cache:
                    await _async_set_cache(url_norm, base_html, title)
                    await _async_set_cached_parsed(url_norm, artist)
                return artist

        gids = _discover_gids(base_html)
        if not gids:
            gids = ["0"]

        # Prioritize the "Unreleased" tab; identify Art and content-tab GIDs
        gids, art_gid, unreleased_gid, content_tabs = _prioritize_gids(base_html, gids)

        # --- Fetch all GID pages concurrently, then parse to pick best ---
        async def _fetch_gid(gid_val: str) -> tuple[str, str] | None:
            return await _fetch_gid_page(
                url_norm, gid_val, title,
                client=client, timeout=timeout, cache_ttl=cache_ttl,
                use_cache=use_cache, t=t,
            )

        # Start every GID fetch concurrently but consume them in priority
        # order, parsing each as it lands and cancelling the rest once a
        # winner is found. Large trackers expose 15+ tabs; the prioritized
        # (unreleased) tab is almost always index 0, so eagerly completing
        # every fetch downloads megabytes that are thrown away.
        fetch_tasks = [asyncio.create_task(_fetch_gid(g)) for g in gids]

        best_artist: Artist | None = None
        best_eras = 0
        best_html = ""

        try:
            for task in fetch_tasks:
                result = await task
                if result is None:
                    continue
                result_gid, sheet_html = result
                try:
                    name = _resolve_artist_name(title, artist_name)
                    with t.phase("parse"):
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
        finally:
            for task in fetch_tasks:
                task.cancel()
            await asyncio.gather(*fetch_tasks, return_exceptions=True)

        if best_artist and best_eras > 0:
            best_artist.source_url = url

            # Secondary tabs (Art + content tabs) — fetched concurrently,
            # all optional: a failure never fails the request.
            await _load_secondary_tabs(
                best_artist, art_gid, content_tabs, url_norm, title,
                client=client, timeout=timeout, cache_ttl=cache_ttl,
                use_cache=use_cache, t=t,
            )

            with t.phase("cache_write"):
                if write_cache and best_html:
                    await _async_set_cache(url_norm, best_html, title)
                if write_cache:
                    await _async_set_cached_parsed(url_norm, best_artist)
            return best_artist

        # Fallback
        html, title = await async_fetch_sheet_html(
            url, timeout=timeout, cache_ttl=cache_ttl, use_cache=use_cache
        )
        name = _resolve_artist_name(title, artist_name)
        artist = await asyncio.to_thread(parse_sheet, html, name)
        artist.source_url = url
        if write_cache:
            await _async_set_cached_parsed(url_norm, artist)
        return artist

    except httpx.HTTPError as e:
        _raise_fetch_error(e, url)
