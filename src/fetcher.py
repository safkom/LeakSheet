"""LeakSheet — URL fetcher for live Google Sheets tracker data.

Fetches HTML table data from Google Sheets /htmlview URLs and custom
tracker domains (e.g. yetracker.net).

Strategy (async pipeline; the sync entry points are thin wrappers over it):
1. Serve from the parsed-JSON disk cache when fresh.
2. If the URL carries an explicit GID, try that tab first — unless the
   workbook's tab listing classifies it as a content tab (Misc etc.), in
   which case fall through to discovery.
3. Otherwise fetch the base htmlview page, discover all GIDs plus named tabs,
   and fetch every candidate concurrently — consuming results in priority
   order (the "Unreleased" tab first) and cancelling the rest once a winner
   (most eras, minimum threshold) parses.
4. Load secondary tabs concurrently: Art (with pHash verification) and every
   content tab; badge tabs stamp highlights onto existing songs.
5. Cache both the winning HTML and the parsed result; a size-capped eviction
   keeps the cache directory bounded.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse, urlencode

import httpx

logger = logging.getLogger(__name__)

from src.config import (
    ARTISTGRID_URL,
    USER_AGENT,
    register_tracker_hosts,
    sheet_host_allowed,
    tracker_hosts_are_stale,
)
from src.models import Artist, Section, TabSection
from src.streaming import PublicOnlyAsyncTransport
from src.parser import (
    apply_art_tab_images,
    apply_badge_tabs,
    parse_art_tab,
    parse_artistgrid_csv,
    parse_misc_tab,
    parse_sheet,
    _MAX_UNMATCHED_ROWS,
    _disambiguate_era_names,
    _era_match_key,
    _song_match_key,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 60.0  # Large trackers (Ye: 10MB) need time
DEFAULT_CACHE_TTL = 3600  # 1 hour default cache
STALE_CACHE_TTL = 86400  # 24h max age for stale-while-revalidate
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

# Size cap for the sheet HTML + parsed-JSON cache (why: docs/decisions.md; the
# image cache has had a 200MB cap for a while, the sheet cache had none — a
# TrackerHub sweep left ~700MB behind on a 512MB-class box). Oldest entries
# (grouped per hash stem) are evicted first; img_* files have their own cap.
_SHEET_CACHE_MAX_BYTES = int(
    os.environ.get("LEAKSHEET_SHEET_CACHE_MAX_BYTES", str(1024 * 1024 * 1024))
)
_SHEET_EVICT_MIN_INTERVAL = 60.0  # scan the dir at most once a minute
_last_sheet_evict = 0.0
# tempfile.mkstemp(prefix=f"{name}.tmp") → "abc.html.tmpQ7z1zK".
_TMP_SUFFIX_RE = re.compile(r"\.tmp[A-Za-z0-9_]{6,}$")

# Concurrent sub-page fetches, across ALL callers.
#
# Discovery started every discovered GID at once and _aggregate_hub_workbook
# fetched *and parsed* every unclassified tab at once, each holding its full
# response body — the largest export here is 11.85MB, and README.md:147 says
# the box cannot fit two concurrent Ye-sized parses. One semaphore inside
# _fetch_gid_page bounds all three fan-out sites at their single choke point.
_GID_FETCH_CONCURRENCY = int(
    os.environ.get("LEAKSHEET_GID_FETCH_CONCURRENCY", "6") or 6
)
_gid_fetch_sem: asyncio.Semaphore | None = None
# Hub-workbook tabs are fetched AND parsed, so they need a tighter bound.
_HUB_LOAD_CONCURRENCY = int(
    os.environ.get("LEAKSHEET_HUB_LOAD_CONCURRENCY", "3") or 3
)


def _gid_fetch_slot() -> asyncio.Semaphore:
    """Lazily created so the semaphore binds to the running loop."""
    global _gid_fetch_sem
    if _gid_fetch_sem is None:
        _gid_fetch_sem = asyncio.Semaphore(_GID_FETCH_CONCURRENCY)
    return _gid_fetch_sem


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
            # Client-level default so a future call site that forgets an
            # explicit timeout= doesn't silently get httpx's 5s default.
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            # The host allowlist is checked once, up front; this rejects
            # non-public destinations at connect on EVERY redirect hop, so an
            # allowed host cannot 30x the fetch into RFC1918 or link-local.
            transport=PublicOnlyAsyncTransport(retries=1),
        )
    return _sheets_client


async def _refresh_tracker_hosts() -> None:
    """Harvest fetchable hosts from the ArtistGrid feed (best effort).

    Lets a tracker added to the community feed work without a redeploy.
    Self-throttled by ``TRACKER_HOST_REFRESH_INTERVAL`` so a flood of bogus
    hosts can't turn this into an amplifier.
    """
    if not tracker_hosts_are_stale():
        return
    try:
        client = _get_sheets_client()
        resp = await client.get(ARTISTGRID_URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        entries = await asyncio.to_thread(parse_artistgrid_csv, resp.text)
        known = await asyncio.to_thread(
            register_tracker_hosts, [e.url for e in entries]
        )
        logger.info("ArtistGrid host refresh: %d hosts known", known)
    except Exception as e:
        # Never let feed trouble turn a valid tracker URL into a hard error
        # any earlier than it already would be.
        logger.warning("ArtistGrid host refresh failed: %s", e)
        register_tracker_hosts([])  # stamp the attempt so we don't hot-loop


async def _assert_sheet_host_allowed(url: str) -> None:
    """Reject a sheet URL whose host isn't an allowed tracker host.

    Raises :class:`InvalidURLError`, which the API maps to 400.
    """
    host = urlparse(url).hostname
    if sheet_host_allowed(host):
        return
    await _refresh_tracker_hosts()
    if sheet_host_allowed(host):
        return
    raise InvalidURLError(
        f"host not allowed for tracker fetching: {host}. Trackers listed on "
        f"ArtistGrid are accepted automatically; add others via "
        f"LEAKSHEET_EXTRA_SHEET_HOSTS."
    )


# Regex to extract sheet GIDs from the htmlview page JS
GID_PATTERN = re.compile(r"gid[=:]\s*[\"']?(\d+)")

# Regex to extract (name, gid) pairs from the items.push() JS in htmlview pages.
# Google Sheets embeds tab metadata as:
#   items.push({name: "Tab Name", pageUrl: "...", gid: "12345", ...});
_TAB_ITEMS_PATTERN = re.compile(
    r'\{name:\s*"([^"]+)"[^}]*?gid:\s*"(\d+)"',
)

# The same items.push() switcher, but keyed on pageUrl instead of gid.
#
# CORRECTION (verified by live-fetching all three hosts): deftonestracker.net,
# franktracker.net and tylertracker.net all DO emit `gid:` on every entry, so
# _discover_named_tabs already found their tabs and the name-merge below is a
# no-op for them. The load-bearing half of this feature is _build_sheet_html_url
# preferring the advertised PATH — those hosts answer the ?gid= query form with
# a table-less shell page. The merge is kept as a cheap fallback for a host that
# genuinely omits gid; it has not been observed.
#   items.push({name: "Unreleased", pageUrl: "\/htmlview\/sheet\/554276433.html"});
#   items.push({name: "Unreleased", pageUrl: "\/preview\/sheet\/937104017.html"});
# Those hosts answer the ?gid= query form with the 52KB shell page — no
# <table> — so every one of them failed with NoTablesError until we followed
# the URL the page itself advertises.
_TAB_PAGEURL_PATTERN = re.compile(
    r'\{name:\s*"([^"]+)"[^}]*?pageUrl:\s*"([^"]+)"',
)

# Trailing gid in a page-switcher path: "/htmlview/sheet/554276433.html".
_PAGEURL_GID_PATTERN = re.compile(r"/(\d+)\.html?$")

# Art tab name keywords (after stripping emojis and normalising whitespace)
_ART_TAB_NAMES = frozenset({"art", "album art", "cover art", "artwork", "arts", "album arts"})

# Secondary content tabs parsed into Artist.misc_entries. Keys are cleaned
# tab names (emoji stripped, lowercased); values are the source_tab kind.
_MISC_TAB_NAMES = frozenset({"misc", "misc.", "miscellaneous"})
_MUSIC_VIDEO_TAB_NAMES = frozenset({"music videos", "music video", "videos", "mvs"})

# Extra content tabs — see docs/decisions.md::fetcher.py::extra-tab-grammars
_RELEASED_TAB_NAMES = frozenset({"released"})
_BEST_OF_TAB_NAMES = frozenset({"best of"})
_WORST_OF_TAB_NAMES = frozenset({"worst of"})
_STEMS_TAB_NAMES = frozenset({"stems"})
_SPECIAL_TAB_NAMES = frozenset({"special", "notable"})
# On-streaming catalogues, split out from the unreleased tab (Smino).
_STREAMING_TAB_NAMES = frozenset({"streaming", "on streaming"})
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

# Badge tab kinds — see docs/decisions.md::fetcher.py::badge-tab-kinds
_BADGE_TAB_KINDS = frozenset({"best_of", "worst_of", "special", "grails", "wanted"})

# Tabs deliberately NOT parsed — duplicates of the main tab, bespoke non-song
# grammars, and lookup tables. A named set rather than a comment because the
# hub-workbook aggregation needs the same exclusions. Why: docs/decisions.md.
_EXCLUDED_TAB_NAMES = frozenset({
    "recent", "recents", "recent additions", "what's new", "whats new",
    "tracklists", "tracklist", "album copies", "compilations",
    "groupbuys", "group buys", "buys", "tours", "tour",
    "samples", "og files", "og snippets",
    "key", "legend", "socials", "bpm & keys", "bpm and keys",
    "template", "templates", "credits", "changelog", "changelogs",
    "guidelines", "tracker guidelines", "info", "about", "rules", "faq",
    "planned", "shared", "form", "forms",
})

# Main tab identification, fetch priority — see docs/decisions.md::fetcher.py::unreleased-tab-priority
_UNRELEASED_TAB_NAMES = frozenset({
    "unreleased", "leaks", "leaked", "unreleased songs",
    "leaked songs", "all unreleased", "all unreleased songs",
    "all leaks", "main", "tracker",
    # Trackers that split streaming from non-streaming name the primary tab
    # for the split rather than plainly "Unreleased" (Smino).
    "off-streaming / unreleased", "unreleased / off-streaming",
    "off streaming / unreleased", "unreleased / off streaming",
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


def _build_sheet_html_url(
    base_url: str, gid: str, page_paths: dict[str, str] | None = None
) -> str:
    """Build the URL that returns this tab's server-rendered HTML.

    When the base page carried a switcher naming this gid's path, use it —
    that is the URL the host actually serves. Otherwise fall back to the
    query form:

    For Google Sheets: /spreadsheets/d/{id}/htmlview/sheet?headers=true&gid={gid}
    For custom domains: /htmlview/sheet?headers=true&gid={gid}
    """
    parsed = urlparse(base_url)

    if page_paths and (path := page_paths.get(gid)):
        if path.startswith(("http://", "https://")):
            return path
        return f"{parsed.scheme}://{parsed.netloc}/{path.lstrip('/')}"

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
    # Hosts whose switcher entries carry no `gid:` key still name every tab —
    # without this they fell through to keyword-guessing against nothing, so
    # art/content/unreleased detection never fired for them.
    for gid, (name, _path) in _discover_page_urls(html).items():
        if name:
            result.setdefault(gid, name)
    return result


def _discover_page_urls(html: str) -> dict[str, tuple[str, str]]:
    """Extract {gid: (tab_name, page_path)} from the page-switcher JS.

    The switcher is authoritative: it is what the page's own tab bar uses, so
    it gives both the exact tab name and a URL known to serve that tab.
    """
    result: dict[str, tuple[str, str]] = {}
    for name, raw_path in _TAB_PAGEURL_PATTERN.findall(html):
        path = _decode_js_string(raw_path).strip()
        m = _PAGEURL_GID_PATTERN.search(path)
        if m:
            result.setdefault(m.group(1), (_decode_js_string(name).strip(), path))
    return result


def _page_path_map(html: str) -> dict[str, str]:
    """{gid: page_path} — the subset of `_discover_page_urls` the fetcher needs."""
    return {gid: path for gid, (_name, path) in _discover_page_urls(html).items()}


def _clean_tab_name(name: str) -> str:
    """Normalize a sheet tab name for keyword MATCHING (strip emoji, lower).

    Also strips trailing '(WIP)'-style qualifiers and normalizes slash
    spacing. The one normalizer for matching — see docs/decisions.md for what
    broke when a second copy drifted. Use _display_tab_name for anything a
    user sees; this one lowercases.
    """
    clean = _EMOJI_RE.sub(" ", name).strip().lower()
    clean = re.sub(r"[\(\[][^)\]]*[\)\]]\s*$", "", clean).strip()
    clean = re.sub(r"\s*/\s*", " / ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _display_tab_name(name: str) -> str:
    """Tab name fit for display — emoji stripped, the tracker's casing kept.

    `_clean_tab_name` is for *matching*, so it lowercases and drops '(WIP)'
    suffixes; running .title() back over it mangles real names ("OG Files" →
    "Og Files"). Section headers use this instead.
    """
    return re.sub(r"\s+", " ", _EMOJI_RE.sub(" ", name)).strip()


def _get_unreleased_tab_gid(named_tabs: dict[str, str]) -> str | None:
    """Return the GID of the main unreleased/leaks tab if one exists.

    Used to prefer the primary tracker sheet over landing/recent tabs like
    Travis Scott's "Recent" sheet. Normalises through _clean_tab_name, so
    the '(WIP)' strip applies here too — "Unreleased (WIP)" (Mag.Lo) was
    invisible to this check while every other classifier saw it.
    """
    for gid, name in named_tabs.items():
        if _clean_tab_name(name) in _UNRELEASED_TAB_NAMES:
            return gid
    return None


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
    (_STREAMING_TAB_NAMES, "streaming"),
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
        # Skip in-flight atomic writes. `abc.html.tmpQ7z1`.split(".", 1)[0] is
        # "abc", so temp files grouped with the real entry and got unlinked
        # mid-write — os.replace then raised FileNotFoundError out of
        # _set_cache and 500'd a request that had already parsed successfully.
        if _TMP_SUFFIX_RE.search(path.name):
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


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a same-directory temp file + rename, so a concurrent
    reader never observes a truncated/partial file mid-write."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _set_cache(url: str, html: str, title: str) -> None:
    """Write HTML and metadata to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url)
    # Atomic: these files are read without a lock, and a background
    # revalidation rewriting one while a request reads it produced a torn
    # read. For the parsed cache that reached the client as truncated JSON
    # under a 200 (get_cached_parsed_bytes does no validation).
    _atomic_write_text(CACHE_DIR / f"{key}.html", html)
    # Merge, don't overwrite. `.html` and `.parsed.json` share one meta file
    # but have independent lifecycles: this writes minutes before the parse
    # exists, and can be followed by a failure that never produces one.
    # Rebuilding the dict here bumped the parsed cache's freshness to "now"
    # and dropped its content_hash, so a failed refresh served yesterday's
    # parse as a fresh hit for a full TTL.
    _write_meta(key, {"url": url, "title": title, "timestamp": time.time()})
    _maybe_evict_sheet_cache()


def _read_meta(key: str) -> dict:
    """Read a cache entry's metadata, or {} when absent/corrupt."""
    try:
        return json.loads((CACHE_DIR / f"{key}.meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(key: str, updates: dict) -> None:
    """Merge `updates` into the entry's metadata and write it atomically."""
    meta = _read_meta(key)
    meta.update(updates)
    _atomic_write_text(
        CACHE_DIR / f"{key}.meta.json", json.dumps(meta, ensure_ascii=False)
    )


def _parsed_timestamp(meta: dict) -> float:
    """Freshness of the PARSED cache.

    Distinct from `timestamp`, which tracks the HTML. Falls back to it for
    entries written before the two were separated.
    """
    ts = meta.get("parsed_timestamp")
    return float(ts) if ts else float(meta.get("timestamp", 0) or 0)


def _get_cached_parsed(url: str, cache_ttl: float = DEFAULT_CACHE_TTL) -> Artist | None:
    """Return cached Artist from parsed JSON if fresh, else None."""
    key = _cache_key(url)
    parsed_file = CACHE_DIR / f"{key}.parsed.json"
    meta_file = CACHE_DIR / f"{key}.meta.json"
    if parsed_file.exists() and meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            if time.time() - _parsed_timestamp(meta) < cache_ttl:
                data = json.loads(parsed_file.read_text(encoding="utf-8"))
                return Artist.model_validate(data)
        except Exception as e:
            # Any unreadable/invalid cache entry (corrupt JSON, IO error,
            # pydantic schema drift after a model change) is a cache miss —
            # never let cache corruption break a request.
            logger.warning("Parsed cache read failed for %s: %s", url[:80], e)
    return None


# A parse returning less than this share of the cached entry's tracks is
# treated as a partial fetch rather than a real edit to the sheet.
CACHE_COLLAPSE_RATIO = 0.8


def _collapse_reason(key: str, data: dict) -> str | None:
    """Why ``data`` must not overwrite the cached parse, or None if it may.

    A partial fetch — some tabs short, or a sibling workbook that failed to
    load — parses cleanly and looks like any other result, so it was cached and
    then served by stale-while-revalidate until something forced a refresh. The
    Ye tracker sat at 5,817 tracks across 36 eras for exactly that reason, with
    its era order scrambled by the partial merge, while a fresh parse of the
    same URL gave 9,382 across 44.

    The old entry is preferred only while it is still worth something: past
    ``STALE_CACHE_TTL`` it would not be served anyway, so a tracker that
    genuinely shrank recovers on its own rather than being frozen forever.
    """
    parsed_file = CACHE_DIR / f"{key}.parsed.json"
    if not parsed_file.exists():
        return None
    try:
        previous = json.loads(parsed_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(previous, dict):
        return None

    old = previous.get("total_versions") or 0
    new = data.get("total_versions") or 0
    if old <= 0 or new >= old * CACHE_COLLAPSE_RATIO:
        return None

    try:
        meta = json.loads((CACHE_DIR / f"{key}.meta.json").read_text())
        age = time.time() - _parsed_timestamp(meta)
    except (OSError, json.JSONDecodeError, TypeError):
        age = 0.0
    if age > STALE_CACHE_TTL:
        return None

    old_eras = len(previous.get("eras") or [])
    new_eras = len(data.get("eras") or [])
    return (
        f"{new} tracks / {new_eras} eras vs cached {old} / {old_eras}"
    )


def _set_cached_parsed(url: str, artist: Artist) -> None:
    """Write parsed Artist JSON to cache, with content hash in metadata."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url)
    try:
        data = artist.model_dump()
        reason = _collapse_reason(key, data)
        if reason is not None:
            # Served to this caller, but not persisted: the good copy stays,
            # and the next request is not poisoned by a transient failure.
            logger.warning(
                "Refusing to cache a collapsed parse for %s (%s)", url[:80], reason
            )
            return
        _atomic_write_text(
            CACHE_DIR / f"{key}.parsed.json",
            json.dumps(data, ensure_ascii=False),
        )
        # parsed_timestamp, not timestamp: the parse's freshness is its own
        # signal. Under force_refresh the caller skips _set_cache entirely
        # while still writing the parse, so without a write here a
        # pull-to-refresh either inherited the OLD timestamp — fresh data
        # considered stale immediately — or, on a first-ever fetch, wrote a
        # parsed cache that could never be read.
        _write_meta(key, {
            "content_hash": compute_content_hash(data),
            "parsed_timestamp": time.time(),
        })
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
        ts = _parsed_timestamp(meta)
        if not url or ts <= 0:
            continue
        age = now - ts
        if DEFAULT_CACHE_TTL < age <= STALE_CACHE_TTL:
            candidates.append((age, url))
    candidates.sort()
    return [url for _, url in candidates[:limit]]


def clear_cache() -> tuple[int, int]:
    """Remove all cached files (sheet HTML/parsed JSON and resized images).

    Returns ``(cleared, skipped)``. A file that can't be unlinked
    (permissions, a race with concurrent eviction) is skipped and logged
    rather than aborting the sweep partway through.
    """
    if not CACHE_DIR.exists():
        return 0, 0
    cleared = 0
    skipped = 0
    for f in CACHE_DIR.iterdir():
        # Same reason as the eviction scan: unlinking another thread's
        # in-flight atomic write makes its os.replace raise.
        if f.is_file() and not _TMP_SUFFIX_RE.search(f.name):
            try:
                f.unlink()
                cleared += 1
            except OSError as exc:
                skipped += 1
                logger.warning("cache clear: could not delete %s: %s", f.name, exc)
    return cleared, skipped


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
            ts = _parsed_timestamp(meta)
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
        ts = _parsed_timestamp(meta)
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
) -> tuple[list[str], str | None, str | None, list[tuple[str, str, str]], dict[str, str]]:
    """Reorder GIDs so the main tracker tab is tried first.

    Returns (reordered_gids, art_gid, unreleased_gid, content_tabs,
    named_tabs) where
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
    return gids, art_gid, unreleased_gid, content_tabs, named_tabs


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
    await _assert_sheet_host_allowed(url)

    client = _get_sheets_client()
    try:
        if gid:
            sheet_url = _build_sheet_html_url(url, gid)
            # Read the SAME key the write below uses. Reading the base `url`
            # here meant a gid request never hit its own entry (permanent cold
            # fetch) and, worse, could match a base-keyed entry written by the
            # fallback loop — handing back a different tab as the workbook.
            if use_cache and cache_ttl > 0:
                cached = await _async_get_cached(sheet_url, cache_ttl)
                if cached is not None:
                    return cached
            r = await client.get(sheet_url, timeout=timeout)
            r.raise_for_status()
            title_match = TITLE_PATTERN.search(r.text)
            title = title_match.group(1) if title_match else ""
            if use_cache:
                # Key by the URL actually fetched, like every other call site
                # (_fetch_gid_page uses sheet_url). Keying by the base `url`
                # filed one tab's HTML under the workbook's entry, so a later
                # gid-less read — the fallback path in async_fetch_and_parse —
                # got that tab back as if it were the whole sheet.
                await _async_set_cache(sheet_url, r.text, title)
            return r.text, title

        # Step 1: Fetch the base page (cached under the base URL, which is
        # what this branch both reads and writes).
        if use_cache and cache_ttl > 0:
            cached = await _async_get_cached(url, cache_ttl)
            if cached is not None:
                return cached
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
        page_paths = _page_path_map(base_html)
        gids = _discover_gids(base_html) or list(page_paths)
        if not gids:
            gids = ["0"]

        # Step 3: Try each GID
        last_error = None
        for try_gid in gids:
            try:
                sheet_url = _build_sheet_html_url(url, try_gid, page_paths)
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
    page_paths: dict[str, str] | None = None,
) -> tuple[str, str] | None:
    """Fetch a single GID sheet page. Returns (gid, html) or None."""
    try:
        async with _gid_fetch_slot():
            with t.phase("gid_fetch"):
                sheet_url = _build_sheet_html_url(url_norm, gid_val, page_paths)
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
    page_paths: dict[str, str] | None = None,
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
            use_cache=use_cache, t=t, page_paths=page_paths,
        )

    async def _load_art() -> None:
        try:
            with t.phase("art_fetch"):
                art_result = await _fetch(art_gid)
            if art_result:
                _, art_html = art_result
                with t.phase("art_parse"):
                    art_map = await asyncio.to_thread(parse_art_tab, art_html, url_norm)
                if art_map:
                    apply_art_tab_images(artist, art_map)
        except Exception as e:
            # Art tab optional — keep existing art_url on failure. WARNING so
            # a systematically broken tab is visible at default log level.
            logger.warning("Art tab load failed for %s: %s", url_norm[:80], e)

    tab_results: dict[str, list] = {}

    async def _load_tab(gid_val: str, kind: str) -> None:
        try:
            with t.phase("misc_fetch"):
                result = await _fetch(gid_val)
            if result:
                _, tab_html = result
                with t.phase("misc_parse"):
                    tab_results[gid_val] = await asyncio.to_thread(
                        parse_misc_tab, tab_html, kind,
                        [era.name for era in artist.eras],
                    )
        except Exception as e:
            # Content tabs optional; WARNING keeps systematic failures visible.
            logger.warning("Content tab %s load failed: %s", gid_val, e)

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


def _hub_workbook_candidates(
    named_tabs: dict[str, str], skip_gids: set[str | None]
) -> list[tuple[str, str]]:
    """Sibling tabs worth parsing as extra catalogue pages, in tab order.

    ``skip_gids`` is everything already handled elsewhere — the winning tab,
    the hub itself, Art, every classified content tab. What is left, minus
    the deliberately-excluded non-song tabs, is unclassified — which in a hub
    workbook is exactly where the songs live.
    """
    return [
        (gid, name)
        for gid, name in named_tabs.items()
        if gid not in skip_gids
        and _clean_tab_name(name) not in _EXCLUDED_TAB_NAMES
    ]


_PARSE_METADATA_COUNTERS = (
    "total_rows", "song_rows", "skipped_rows", "footer_rows",
    "other_rows", "fuzzy_matched_rows", "unmatched_rows_total",
)


def _merge_parse_metadata(artist: Artist, extra: Artist) -> None:
    """Fold a sibling tab's row accounting into the artist's.

    Without this, ``parse_metadata`` would describe only the winning tab while
    ``eras`` spans several, silently breaking the row-accounting identity
    (total == song + skipped + footer + other) that makes data loss
    measurable — and the skipped-ratio health check with it.
    """
    base, more = artist.parse_metadata, extra.parse_metadata
    if more is None:
        return
    if base is None:
        artist.parse_metadata = more.model_copy(deep=True)
        return
    for f in _PARSE_METADATA_COUNTERS:
        setattr(base, f, getattr(base, f) + getattr(more, f))
    # unmatched_rows is a capped sample, not a total — keep the same cap.
    room = _MAX_UNMATCHED_ROWS - len(base.unmatched_rows)
    if room > 0:
        base.unmatched_rows.extend(more.unmatched_rows[:room])
    for col in more.dropped_columns:
        if col not in base.dropped_columns:
            base.dropped_columns.append(col)


def _merge_aggregated_eras(artist: Artist, tab_name: str, extra: Artist) -> int:
    """Fold one sibling tab's eras into *artist*. Returns songs merged.

    An era the artist already has gains a `Section` named after the tab, so
    the tracker's own grouping stays visible ("Pre-True" carries an
    "Instrumentals & Acapellas" section). An era it doesn't have is appended
    whole — its name is already unique to that tab, so a section header
    would only add noise.
    """
    by_key = {_era_match_key(era.name): era for era in artist.eras}
    merged = 0
    for era in extra.eras:
        songs = [song for section in era.sections for song in section.songs]
        if not songs:
            continue
        target = by_key.get(_era_match_key(era.name))
        if target is None:
            artist.eras.append(era)
            by_key[_era_match_key(era.name)] = era
        else:
            # Reuse a same-named section rather than adding a second one:
            # the iOS row id is era+group+name, so a duplicate name silently
            # drops rows from the list.
            existing = next(
                (s for s in target.sections if s.name == tab_name and not s.group),
                None,
            )
            if existing is not None:
                existing.songs.extend(songs)
            else:
                target.sections.append(Section(name=tab_name, songs=songs))
        merged += len(songs)
    if merged:
        _merge_parse_metadata(artist, extra)
    return merged


async def _aggregate_hub_workbook(
    artist: Artist,
    candidates: list[tuple[str, str]],
    url_norm: str,
    title: str,
    *,
    client: httpx.AsyncClient,
    timeout: float,
    cache_ttl: float,
    use_cache: bool,
    t: PhaseTimer,
    page_paths: dict[str, str] | None = None,
) -> int:
    """Merge sibling catalogue tabs into a hub workbook's era tree.

    A few workbooks use their main tab as a hub of category descriptions and
    split the catalogue across sibling tabs that each use the ordinary era
    grammar (Avicii: "Avicii Leaks", "Unreleased", "Rare & Lost", …). Those
    tabs match no keyword set, so nothing else picks them up and the tracker
    parses to a fraction of its songs.

    Only reached when the main tab is a hub — see the `hub_gid` gate in
    async_fetch_and_parse. Best-effort throughout: a failure is logged and
    the request still returns whatever the winning tab produced.
    """
    if not candidates:
        return 0

    # A SECOND, smaller bound around fetch+parse together. The gid-fetch
    # semaphore is released once the body is in hand, so without this every
    # candidate proceeded to hold its full HTML and build a model tree
    # concurrently. Distinct semaphore, always acquired outside the inner one,
    # so the nesting can't deadlock.
    sem = asyncio.Semaphore(_HUB_LOAD_CONCURRENCY)

    async def _load(gid_val: str, display: str) -> tuple[str, Artist] | None:
        async with sem:
          try:
              result = await _fetch_gid_page(
                  url_norm, gid_val, title, client=client, timeout=timeout,
                  cache_ttl=cache_ttl, use_cache=use_cache, t=t,
                  page_paths=page_paths,
              )
              if result is None:
                  return None
              with t.phase("hub_parse"):
                  parsed = await asyncio.to_thread(parse_sheet, result[1], artist.name, url_norm)
              return display, parsed
          except Exception as e:
              logger.warning("Hub tab %s (%s) failed: %s", gid_val, display, e)
              return None

    loaded = await asyncio.gather(*[_load(g, n) for g, n in candidates])

    # Duplicate-tab filtering — see docs/decisions.md::fetcher.py::duplicate-tab-keys
    def _keys(a: Artist) -> set[str]:
        return {
            k
            for era in a.eras
            for section in era.sections
            for song in section.songs
            if (k := _song_match_key(song.base_name))
        }

    main_keys = _keys(artist)
    total = 0
    for entry in loaded:
        if entry is None:
            continue
        display, extra = entry
        keys = _keys(extra)
        if keys and keys <= main_keys:
            logger.debug("Hub tab %r adds nothing new — skipped", display)
            continue
        merged = _merge_aggregated_eras(artist, _display_tab_name(display), extra)
        main_keys |= keys
        total += merged
        logger.debug("Hub tab %r merged %d songs", display, merged)
    if total:
        logger.info(
            "Hub workbook %s: merged %d songs from %d sibling tabs",
            url_norm[:80], total, len(candidates),
        )
    return total


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
    await _assert_sheet_host_allowed(url_norm)

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
            # Base-page tab listing needed — see docs/decisions.md::fetcher.py::gid-subpage-discovery
            named_tabs: dict[str, str] = {}
            base_page_paths: dict[str, str] = {}
            try:
                with t.phase("base_fetch"):
                    base_resp = await client.get(url_norm, timeout=timeout)
                    base_resp.raise_for_status()
                named_tabs = _discover_named_tabs(base_resp.text)
                base_page_paths = _page_path_map(base_resp.text)
            except httpx.HTTPError:
                pass  # Can't tell — fall back to trusting parse_sheet below
            gid_is_misc_tab = gid in {g for g, _kind, _n in _get_content_tabs(named_tabs)}
            if not gid_is_misc_tab:
                name = _resolve_artist_name(title, artist_name)
                with t.phase("parse"):
                    artist = await asyncio.to_thread(parse_sheet, html, name, url_norm)
                # Eras alone aren't enough — a hub tab parses to eras with no
                # songs, and accepting it here would skip discovery entirely.
                gid_songs = sum(
                    len(s.songs) for era in artist.eras for s in era.sections
                )
                if artist.eras and gid_songs:
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
                            page_paths=base_page_paths,
                        )
                        if write_cache:
                            await _async_set_cached_parsed(url_norm, artist)
                        return artist
                    # A better "Unreleased" tab exists — fall through to full discovery
                # GID produced 0 eras or 0 songs — fall through to discovery
            # else: gid is the Misc/Music-Videos tab — fall through to full discovery,
            # see docs/decisions.md::fetcher.py::gid-subpage-discovery
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
                artist = await asyncio.to_thread(parse_sheet, base_html, name, url_norm)
            if artist.eras:
                artist.source_url = url
                if write_cache:
                    await _async_set_cache(url_norm, base_html, title)
                    await _async_set_cached_parsed(url_norm, artist)
                return artist

        # The page-switcher is authoritative for both tab names and sub-page
        # URLs — see _discover_page_urls.
        page_paths = _page_path_map(base_html)
        gids = _discover_gids(base_html) or list(page_paths)
        if not gids:
            gids = ["0"]

        # Prioritize the "Unreleased" tab; identify Art and content-tab GIDs
        gids, art_gid, unreleased_gid, content_tabs, named_tabs = _prioritize_gids(
            base_html, gids
        )

        # --- Fetch all GID pages concurrently, then parse to pick best ---
        async def _fetch_gid(gid_val: str) -> tuple[str, str] | None:
            return await _fetch_gid_page(
                url_norm, gid_val, title,
                client=client, timeout=timeout, cache_ttl=cache_ttl,
                use_cache=use_cache, t=t, page_paths=page_paths,
            )

        # Priority-ordered concurrent fetch with cancellation — see
        # docs/decisions.md::fetcher.py::gid-fetch-priority
        fetch_tasks = [asyncio.create_task(_fetch_gid(g)) for g in gids]

        best_artist: Artist | None = None
        # Rank tuple order — see docs/decisions.md::fetcher.py::gid-fetch-priority
        best_score = (0, 0, 0)
        best_gid: str | None = None
        hub_gid: str | None = None
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
                        candidate = await asyncio.to_thread(parse_sheet, sheet_html, name, url_norm)
                    n_eras = len(candidate.eras)
                    n_songs = sum(
                        len(s.songs)
                        for era in candidate.eras
                        for s in era.sections
                    )

                    logger.debug("GID %s → %d eras, %d songs", result_gid, n_eras, n_songs)
                    if n_eras >= 1 and n_songs == 0 and result_gid == unreleased_gid:
                        hub_gid = result_gid
                    # Songs outrank eras. Era count used to come first, as a
                    # proxy for "properly structured tab", but it stopped being
                    # one once flat-era tabs (no header rows, era implied by the
                    # Era column) started yielding real era counts: a 5-era,
                    # 7-song badge sub-tab then outranked the 3-era, 474-song
                    # main tab on the MIKE tracker, and 43 flat eras beat 26 real
                    # ones on Dr. Dre — costing 668 songs and every era cover.
                    # The payload is songs; rank on it.
                    score = (1 if n_songs else 0, n_songs, n_eras)
                    if score > best_score:
                        best_score = score
                        best_artist = candidate
                        best_gid = result_gid
                        best_html = sheet_html

                    if n_songs == 0:
                        continue  # never short-circuit on a song-less tab
                    # Unreleased tab wins as long as it has at least 1 era —
                    # prevents Recents/landing tabs from outcompeting it on era count.
                    if result_gid == unreleased_gid:
                        logger.debug("Selected unreleased GID %s (%d eras)", result_gid, n_eras)
                        break
                    elif n_eras >= _MIN_ERAS_FOR_VALID_GID and score == best_score:
                        # Only stop early on a tab that is actually leading.
                        # This break abandons every gid still in flight, so a
                        # small tab that merely clears the era floor must not
                        # trigger it — that is how a 7-song sub-tab pre-empted
                        # a 474-song main tab.
                        break
                except (ValueError, KeyError):
                    continue
        finally:
            for task in fetch_tasks:
                task.cancel()
            await asyncio.gather(*fetch_tasks, return_exceptions=True)

        if best_artist and best_score[1] > 0:
            best_artist.source_url = url

            # Hub workbook: the main tab held no songs, so the catalogue is
            # spread across unclassified sibling tabs. Gated on that, so a
            # healthy tracker never pays for the extra fetches.
            if hub_gid is not None:
                await _aggregate_hub_workbook(
                    best_artist,
                    _hub_workbook_candidates(
                        named_tabs,
                        {best_gid, hub_gid, art_gid}
                        | {g for g, _k, _n in content_tabs},
                    ),
                    url_norm, title,
                    client=client, timeout=timeout, cache_ttl=cache_ttl,
                    use_cache=use_cache, t=t, page_paths=page_paths,
                )

            # Secondary tabs (Art + content tabs) — fetched concurrently,
            # all optional: a failure never fails the request.
            await _load_secondary_tabs(
                best_artist, art_gid, content_tabs, url_norm, title,
                client=client, timeout=timeout, cache_ttl=cache_ttl,
                use_cache=use_cache, t=t, page_paths=page_paths,
            )

            # Re-run AFTER every merge. parse_sheet guarantees unique era names
            # for one tab, but _merge_aggregated_eras and _load_secondary_tabs
            # append sibling tabs' eras to this list afterwards — so the served
            # artist could still carry a duplicate, which is the one thing
            # clients cannot survive (SwiftUI drops the second row silently).
            # Idempotent: names already unique are returned untouched.
            best_artist.eras = _disambiguate_era_names(best_artist.eras)

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
        artist = await asyncio.to_thread(parse_sheet, html, name, url)
        artist.source_url = url
        if write_cache:
            await _async_set_cached_parsed(url_norm, artist)
        return artist

    except httpx.HTTPError as e:
        _raise_fetch_error(e, url)
