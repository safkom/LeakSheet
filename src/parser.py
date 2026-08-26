"""LeakSheet — HTML parser for Google Sheets tracker exports.

Parses the htmlview export of a Google Spreadsheet music tracker into
structured Artist/Era/Song/SongVersion objects.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from functools import lru_cache
from typing import Iterable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

logger = logging.getLogger(__name__)

from src.config import COLUMN_ALIASES
from src.models import (
    Artist,
    Badge,
    EMOJI_RUN_RE,
    Era,
    MiscEntry,
    Notice,
    ParseMetadata,
    Section,
    Song,
    SongVersion,
    SourceRef,
    TrackerEntry,
    TrackerStats,
    VERSION_TAG_PATTERN,
    _split_alt_aliases,
    extract_badge,
    extract_og_filenames,
    extract_samples,
    strip_og_filename_lines,
    extract_version_tag,
    parse_era_stats,
    parse_highlighted_producers,
    parse_song_credits,
    parse_timeline,
    parse_tracker_stats,
    slugify,
    version_sort_key,
)


# ---------------------------------------------------------------------------
# Parser tuning constants
# ---------------------------------------------------------------------------

# Maximum number of rows to scan when looking for the header row.
# Some trackers have instruction/title rows before the actual column headers.
_MAX_HEADER_SCAN_ROWS = 11

# Cap on unmatched rows recorded for diagnostics — prevents unbounded list growth
# on trackers that have many footers, annotations, or oddly structured rows.
_MAX_UNMATCHED_ROWS = 50


# ---------------------------------------------------------------------------
# Low-level HTML table extraction
# ---------------------------------------------------------------------------

class _TableExtractor(HTMLParser):
    """Extract rows from every <table> in a Google Sheets HTML export.

    Each row is a list of _Cell objects containing text, links, and images.
    """

    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_td = False
        self.in_tr = False
        self.in_a = False
        self.rows: list[list[_Cell]] = []
        self._current_row: list[_Cell] = []
        self._cell_text = ""
        self._cell_links: list[str] = []
        self._cell_images: list[str] = []
        # Created again per <td>, but it is READ in the </td> branch, so a
        # stray closing tag before any opening one would AttributeError.
        self._cell_link_lines: list[int] = []
        self._colspan = 1
        self._a_href = ""

    # -- handlers --

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_tr = True
            self._current_row = []
        elif tag == "td" and self.in_tr:
            self.in_td = True
            self._cell_text = ""
            self._cell_links = []
            self._cell_link_lines = []
            self._cell_images = []
            try:
                self._colspan = int(a.get("colspan", "1") or "1")
            except (ValueError, TypeError):
                self._colspan = 1
        elif tag == "a" and self.in_td:
            self.in_a = True
            self._a_href = a.get("href", "")
        elif tag == "img" and self.in_td:
            src = a.get("src", "")
            if src:
                self._cell_images.append(src)
            # Use alt text as cell text when present (handles image-based era names)
            alt = a.get("alt", "")
            if alt:
                self._cell_text += alt
        elif tag == "br" and self.in_td:
            self._cell_text += "\n"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.in_a:
            self.in_a = False
            if self._a_href:
                self._cell_links.append(self._a_href)
                self._cell_link_lines.append(self._cell_text.count("\n"))
            self._a_href = ""
        elif tag == "td" and self.in_td:
            self.in_td = False
            cell = _Cell(
                text=self._cell_text.strip(),
                links=list(self._cell_links),
                link_lines=list(self._cell_link_lines),
                images=list(self._cell_images),
            )
            self._current_row.append(cell)
            # Fill colspan with empty cells
            for _ in range(self._colspan - 1):
                self._current_row.append(_Cell())
            self._colspan = 1
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self._current_row:
                self.rows.append(self._current_row)
        elif tag == "table":
            self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.in_td:
            self._cell_text += data


class _Cell:
    """A single table cell with text content, extracted links, and images."""
    __slots__ = ("text", "links", "link_lines", "images")

    def __init__(
        self,
        text: str = "",
        links: list[str] | None = None,
        link_lines: list[int] | None = None,
        images: list[str] | None = None,
    ) -> None:
        self.text = text
        self.links = links or []
        self.link_lines = link_lines or []
        self.images = images or []

    def __repr__(self) -> str:
        parts = [f"Cell({self.text!r}"]
        if self.links:
            parts.append(f", links={len(self.links)}")
        if self.images:
            parts.append(f", imgs={len(self.images)}")
        return "".join(parts) + ")"


try:
    from lxml import etree
    from lxml import html as _lxml_html
except ImportError:  # pragma: no cover - lxml is in requirements
    _lxml_html = None


def _cell_from_td(td) -> _Cell:
    """Build a _Cell from an lxml <td> element.

    Mirrors _TableExtractor semantics exactly: <br> becomes "\\n", img alt
    text joins the cell text, and each link records the line number the
    anchor closes on.
    """
    parts: list[str] = []
    links: list[str] = []
    link_lines: list[int] = []
    images: list[str] = []
    newlines = 0  # running count of "\n" appended so far

    def walk(el) -> None:
        nonlocal newlines
        tag = el.tag
        if not isinstance(tag, str):  # comment / processing instruction
            return
        if tag == "br":
            parts.append("\n")
            newlines += 1
        elif tag == "img":
            src = el.get("src")
            if src:
                images.append(src)
            alt = el.get("alt")
            if alt:
                parts.append(alt)
                newlines += alt.count("\n")
        text = el.text
        if text:
            parts.append(text)
            newlines += text.count("\n")
        for child in el:
            walk(child)
            tail = child.tail
            if tail:
                parts.append(tail)
                newlines += tail.count("\n")
        if tag == "a":
            href = el.get("href")
            if href:
                links.append(href)
                link_lines.append(newlines)

    walk(td)
    return _Cell(
        text="".join(parts).strip(),
        links=links,
        link_lines=link_lines,
        images=images,
    )


def _extract_table_lxml(html_content: str) -> list[list[_Cell]]:
    """Fast table extraction via lxml (≈10x quicker than html.parser)."""
    if not html_content.strip():
        return []
    doc = _lxml_html.fromstring(html_content)
    rows: list[list[_Cell]] = []
    for tr in doc.iter("tr"):
        current: list[_Cell] = []
        for td in tr:
            if td.tag != "td":
                continue
            cell = _cell_from_td(td)
            current.append(cell)
            try:
                colspan = int(td.get("colspan", "1") or "1")
            except (ValueError, TypeError):
                colspan = 1
            for _ in range(colspan - 1):
                current.append(_Cell())
        if current:
            rows.append(current)
    return rows


def extract_table(html_content: str) -> list[list[_Cell]]:
    """Parse HTML and return the rows of every <table> as lists of _Cell.

    Rows from all tables are concatenated in document order (tracker exports
    render one logical table, occasionally split across elements).

    Uses lxml when available (≈10x quicker than html.parser); falls back to
    the stdlib HTMLParser implementation when lxml is absent or rejects the
    input — e.g. lxml raises ValueError for str input that starts with an
    XML declaration (``<?xml …?>``), which some mirrored exports carry.
    """
    rows: list[list[_Cell]] | None = None
    if _lxml_html is not None:
        try:
            rows = _extract_table_lxml(html_content)
        except (etree.ParserError, ValueError):
            rows = None  # malformed for lxml — retry with the lenient stdlib parser
    if rows is None:
        parser = _TableExtractor()
        parser.feed(html_content)
        rows = parser.rows
    return rows


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

def _match_column_alias(key: str) -> str | None:
    """Try to match a normalised key against COLUMN_ALIASES.

    Tries exact match first, then prefix matching for glued-on text
    (e.g. "noteswelcome to..." → "notes").
    """
    canonical = COLUMN_ALIASES.get(key)
    if canonical:
        return canonical
    for alias, canon in COLUMN_ALIASES.items():
        if len(alias) <= 2 or not key.startswith(alias):
            continue
        # Only fire on GLUED text, which is what this fallback is for: a header
        # cell whose label ran into a notice ("noteswelcome to the tracker").
        # When the next character is a space the remainder is a separate word,
        # so the header is a different column that merely starts with an alias
        # — "Project Type" is not the Era column, and "Dates Added" is not the
        # bare "Date" column. Matching those silently binds the wrong column.
        if key[len(alias)] == " ":
            continue
        return canon
    return None


def detect_columns(header_row: list[_Cell]) -> dict[str, int]:
    """Map canonical field names to column indices from the header row.

    Returns e.g. {"era": 0, "name": 1, "notes": 2, "track_length": 3, ...}
    """
    col_map: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        # Normalize: lowercase, strip parenthetical content (which contains links/descriptions)
        raw = cell.text.strip()
        # Take only the first word/phrase before any parenthetical
        paren_idx = raw.find("(")
        if paren_idx > 0:
            raw = raw[:paren_idx]
        key = raw.strip().lower()
        key = re.sub(r'\s+', ' ', key)  # normalize internal whitespace (e.g. 'file \ndate' → 'file date')
        # 2026-07-20 sweep: colon-suffixed headers ('Track Titles:',
        # 'Category:') dropped whole columns across dozens of trackers.
        key = key.rstrip(":").strip()

        canonical = _match_column_alias(key)

        # If no match on the full cell text, try each individual line.
        # Handles cells where the column name appears on a separate line
        # mixed with notice/announcement text (e.g. "[notice]\nNotes").
        if not canonical:
            for line in raw.split("\n"):
                line_key = re.sub(r'\s+', ' ', line.strip().lower())
                if line_key:
                    canonical = _match_column_alias(line_key)
                    if canonical:
                        break

        if canonical and canonical not in col_map:
            col_map[canonical] = idx

    if "name" not in col_map:
        col_map |= _infer_name_column(header_row, col_map)

    return col_map


# Words that identify the song-title column when no alias matched its header.
_NAME_WORD_RE = re.compile(r"\b(title|name)\b", re.IGNORECASE)


def _infer_name_column(
    header_row: list[_Cell], col_map: dict[str, int]
) -> dict[str, int]:
    """Find the song-title column when no alias matched, else return {}.

    Without this, `name` falls back to positional index 1 (see
    `_parse_song_row`), which is blind to layout. Overlord's Lil Uzi Vert
    discography puts a "#:" track-number column there and titles a column
    "Project & Track Title", so all 281 of its songs were named "1", "2", "3".

    Only headers no alias claimed are considered, and only those containing
    "title" or "name" as a whole word — so this cannot steal a column that a
    real alias already resolved.
    """
    taken = set(col_map.values())
    for idx, cell in enumerate(header_row):
        if idx in taken:
            continue
        if _NAME_WORD_RE.search(cell.text):
            return {"name": idx}
    return {}


def _header_label(cell: _Cell) -> str:
    """The comparable label of a header cell: first line, parenthetical cut."""
    first_line = cell.text.strip().split("\n")[0].strip()
    paren = first_line.find("(")
    if paren > 0:
        first_line = first_line[:paren].strip()
    return first_line[:60]


def detect_dropped_columns(
    header_row: list[_Cell], col_map: dict[str, int]
) -> tuple[list[str], list[str]]:
    """Header cells whose values never reach the model, split by reason.

    Returns ``(unknown, duplicate)``.

    *unknown* is a header no alias covers — a layout nobody has taught the
    parser, and the list worth reading when a new tracker looks wrong.

    *duplicate* is a header an alias DOES cover, whose canonical field a
    different column already claimed: a sheet with two "Name" columns, or with
    both "Available" and "In Circulation". Its values are lost just as
    silently, but the cause is the sheet's shape rather than a gap in the
    aliases, and no amount of alias work will change it. Reported together they
    were indistinguishable, and 11 of the corpus's most frequent "dropped"
    headers were this kind — noise in the one diagnostic that exists to find
    real gaps.
    """
    mapped = set(col_map.values())
    unknown: list[str] = []
    duplicate: list[str] = []
    for idx, cell in enumerate(header_row):
        if idx in mapped:
            continue
        label = _header_label(cell)
        if not label:
            continue
        key = re.sub(r"\s+", " ", label.strip().lower()).rstrip(":").strip()
        (duplicate if _match_column_alias(key) else unknown).append(label)
    return unknown, duplicate


def _extract_header_notices(
    header_row: list[_Cell],
    pre_header_rows: list[list[_Cell]],
    artist_name: str,
) -> list[Notice]:
    """Extract announcement/notice text from header cells and pre-header rows.

    Notices are lines in header cells that don't match any known column alias,
    plus any substantial text from rows above the column header row.
    Each link is associated with the specific line it appears on via link_lines.

    Returns a deduplicated list of Notice objects.
    """
    # Keywords that indicate an urgent/alert notice (vs informational links)
    _ALERT_KEYWORDS = re.compile(
        r"not working|shut down|shutdown|expired|broken|taken down|"
        r"dmca|copyright|removed|reuploaded?|reupload|unavailable|"
        r"\bdown\b.*(?:fix|working|progress|eta)|"
        r"(?:fix|working on).*(?:asap|soon|eta)|"
        r"\bno eta\b|in.progress.of",
        re.IGNORECASE,
    )

    notices: list[Notice] = []
    seen: set[str] = set()

    def _clean(text: str) -> str:
        text = text.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()
        return text

    def _is_alert(text: str) -> bool:
        return bool(_ALERT_KEYWORDS.search(text))

    def _add(text: str, link: str | None = None) -> None:
        text = _clean(text)
        if len(text) < 10:
            return
        key = text.lower()
        if key not in seen:
            seen.add(key)
            kind = "alert" if _is_alert(text) else "info"
            notices.append(Notice(text=text, link=link, kind=kind))

    # --- Header cell notices ---
    for cell in header_row:
        raw = cell.text.strip()
        if not raw:
            continue
        # Build per-line link mapping: line_index → cleaned URL
        line_link_map: dict[int, str] = {}
        for link_idx, line_num in enumerate(cell.link_lines):
            if link_idx < len(cell.links):
                cleaned = _clean_link(cell.links[link_idx])
                if cleaned:
                    line_link_map[line_num] = cleaned

        lines = raw.split("\n")
        for line_idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            # Normalise for alias matching
            norm = re.sub(r'\s+', ' ', stripped.lower())
            # Remove parenthetical for matching
            p = norm.find("(")
            match_key = norm[:p].strip() if p > 0 else norm
            if _match_column_alias(match_key):
                continue
            _add(stripped, line_link_map.get(line_idx))

    # --- Pre-header rows ---
    artist_lower = artist_name.lower() if artist_name else ""
    for row in pre_header_rows:
        for cell in row:
            text = cell.text.strip()
            if not text:
                continue
            norm = text.lower()
            # Skip if it's just the artist/tracker name
            if norm == artist_lower or "tracker" in norm and len(text) < 40:
                continue
            # Build per-line link mapping
            line_link_map = {}
            for link_idx, line_num in enumerate(cell.link_lines):
                if link_idx < len(cell.links):
                    cleaned = _clean_link(cell.links[link_idx])
                    if cleaned:
                        line_link_map[line_num] = cleaned
            for line_idx, line in enumerate(text.split("\n")):
                _add(line.strip(), line_link_map.get(line_idx))

    return notices


# ---------------------------------------------------------------------------
# Row classification
# ---------------------------------------------------------------------------

# Era stats row forms across 400+ trackers — docs/decisions.md::parser.py::ERA_STATS_PATTERN
#
# Two unrelated vocabularies appear in this one cell, and a tracker uses one or
# the other, never both:
#
#   leak-status  "45 Full / 3 Partial / 4 Snippet(s) / 70 Unavailable"
#   discography  "18 Total / 4 Singles / 7 Album Track(s) / 2 Feature(s)"
#
# Only the first was listed here, so every discography-style era header failed
# _is_era_header and the era — with its cover art, timeline and description —
# was dropped and its songs glued onto the previous era. Measured over 400
# cached tabs: 267 era headers lost across 34 tabs (~9% of all trackers).
#
# The two vocabularies must NOT be matched the same way. Leak-status words are
# distinctive enough to identify a stats cell from a single pair: "5 Full" is
# never anything else. Discography words are ordinary English that shows up in
# era NAMES — "2009 Album", "1977 Sessions", "2020 Throwaways", and the
# "38 Special Sessions" case already pinned in tests. Matching those on one
# pair turned 86 Bonnie McKee song rows into empty eras. A real discography
# block always states several counts, so require two.
ERA_STATS_PATTERN = re.compile(
    r"\d+\s+"
    r"("
    r"OG File|Total Full|Full|Tagged|Partial|Snippet|Stem|Unavailable"
    r"|Edited"                                                          # Michael Jackson
    r"|of Leaks|of Snippets|of Partials|of Recordings|of Unavailable|of Full"
    r"|Leaks?|Snippets?|Partials?"
    r"|Streaming|Off-Streaming|Off Streaming|On Streaming|On-Streaming"
    r"|tracks?|songs?"
    r"|Released|Deleted|Losts?|Privated"
    r")\b",
    re.IGNORECASE,
)

# Release-type counts. Only trusted inside a multi-pair block — see above.
_DISCOGRAPHY_STATS_PATTERN = re.compile(
    r"\d+\s+"
    r"("
    r"Album Tracks?|Mixtape Tracks?|EP Tracks?|OST Tracks?|TV Tracks?"
    r"|Bonus Tracks?|Compilation Tracks?|Loose Tracks?|Reference Tracks?"
    r"|Promo Singles?|Singles?|Albums?"
    r"|Featuring|Features?|Feats?"
    r"|Produsctions?|Productions?"                                      # sic — real typo
    r"|Remix(?:es)?|Instrumentals?|Acapellas?|Loosies|Loosie"
    r"|Intros?|Interludes?|Outros?|Skits?"
    r"|Demos?|Throwaways?|Sessions?|Original Versions?|Originals?"
    r"|Not Avai?la?ble|Removed|Alt\.? Mix"
    # Visual-media counts, from trackers that fold videos into the era block
    # (UPSAHL). Longer form first so the label reads right in a match dump.
    r"|Music Video Snippets?|Music Videos?"
    # "N Total Links" is the global tracker footer, not an era stat — matching
    # it turns the footer row into a phantom era at the bottom of every sheet.
    r"|Total(?!\s+Links)|Others?"
    r")\b",
    re.IGNORECASE,
)

# Any "<int> <word>" pair, used only to count how many counts a cell states.
_STAT_PAIR_RE = re.compile(r"\d+\s+[A-Za-z]")
_MIN_DISCOGRAPHY_PAIRS = 2


def era_stats_match(text: str) -> bool:
    """True if *text* is an era stats block, in either tracker vocabulary."""
    if ERA_STATS_PATTERN.search(text):
        return True
    return (
        bool(_DISCOGRAPHY_STATS_PATTERN.search(text))
        and len(_STAT_PAIR_RE.findall(text)) >= _MIN_DISCOGRAPHY_PAIRS
    )

# Spreadsheet formula errors. These appear in real trackers when a cell's
# formula breaks, and they must never be mistaken for content — a `#REF!` in
# the era-stats column used to hide every era header in the sheet, collapsing
# the whole tracker into one era literally named "#REF!" (Future, 2026-08).
_SPREADSHEET_ERROR_RE = re.compile(
    r"^#(REF|N/A|VALUE|DIV/0|NAME|NULL|NUM|ERROR|GETTING_DATA)[!?]?$",
    re.IGNORECASE,
)


def _is_spreadsheet_error(text: str) -> bool:
    """Return True if *text* is nothing but a spreadsheet error value."""
    return bool(_SPREADSHEET_ERROR_RE.match(text.strip()))


# A cell whose every line reads "<int> <label>" states counts. Whatever the
# vocabulary, it carries no era name — see _is_era_header.
_STAT_ONLY_LINE_RE = re.compile(r"^\d+\s+[A-Za-z][A-Za-z0-9()/&.\-' ]*$")
_MIN_STAT_ONLY_LINES = 2


def _is_stats_only_cell(text: str) -> bool:
    """True if *text* is nothing but "<int> <label>" lines.

    The global stats footer states its counts in several cells at once — leak
    status in one, quality in another, badge totals in a third. Any of them can
    use wording neither stats pattern lists ("99 Album Track", "43 Best Of"), so
    a vocabulary test cannot recognise them. Their SHAPE can: every line is a
    count. Requiring two lines keeps a one-line era name like "38 Special
    Sessions" out of it, which is the case the stats vocabularies are already
    careful about.
    """
    lines = [l for l in (EMOJI_RUN_RE.sub("", ln).strip() for ln in text.split("\n")) if l]
    if len(lines) < _MIN_STAT_ONLY_LINES:
        return False
    return all(_STAT_ONLY_LINE_RE.match(l) for l in lines)


# Row values that indicate a section divider (not a song or era name).
# These strings appear as standalone cell values in the spreadsheet to
# separate song groups (e.g. "surfaced" = officially released material).
SECTION_SEPARATORS = {
    "surfaced", "unsurfaced", "unavailable",
    "og files for released songs & alternate versions",
    "og files for released songs",
    "unknown collaborations",
    # Cross-tracker section labels
    "features", "collaborations", "collaboration", "featured",
    "collaborations & features", "loosies", "guest verses",
    "guest features",
    # Sub-section labels observed across 50+ trackers
    "throwaways", "throwaway",
    "demos", "demo",
    "snippets", "snippet",
    "snippets/unavailable",
    "production", "productions",
    "project", "projects",
    "fake", "fakes",
    "other media", "other",
    "instrumentals", "instrumental",
    "remixes", "remix",
    "stems", "stem bounces",
    "interludes", "interlude",
    "skits", "skit",
    "leaks", "leaked",
    "unreleased", "released",
    "pre-release", "pre release",
    "live performances", "live",
    "recordings",
    "full", "partial",  # Carti-style sub-section labels
    "og files",
    "og files for released songs + alternate mixes",
    "alternate mixes",
}

# Name-column values that signal the start of tracker footer/hub content.
_NAME_FOOTER_KEYWORDS: frozenset[str] = frozenset({
    "carti tracker hub",
})


def _is_era_header(row: list[_Cell]) -> bool:
    """Check if a row is an era header (contains stats pattern in first cell).

    Real era headers have era stats in cell 0 AND an era name somewhere else
    in the row (or as the first line of cell 0 before the stats).
    Global stats rows have stats in ALL cells with no era name — reject those.

    A stats cell holding a spreadsheet error still counts: see
    docs/decisions.md::parser.py::broken-stats-formula.
    """
    if not row:
        return False
    text = row[0].text
    if not era_stats_match(text):
        if not _is_spreadsheet_error(text):
            return False
        # The stats cell is unreadable, so it can carry no evidence either
        # way — require the era name (or the era art) from another cell.
        for c in row[1:]:
            if c.images:
                return True
            first_line = c.text.split("\n")[0].strip()
            if first_line and not re.match(r"^\d+\s", first_line):
                return True
        return False
    # Real era headers have at least one cell (or first line of cell 0) that
    # contains a non-stats era name.  Global stats rows have only stat-like
    # content (numbers + keywords) in every cell.
    _NUMERIC_STAT_RE = re.compile(r"^\d+\s")
    for c in row:
        text = c.text.strip()
        if not text:
            continue
        # Check for images (era art) — a strong signal this is an era header
        if c.images:
            return True
        # A cell that is nothing but counts holds no era name, whatever
        # vocabulary it counts in. Without this the sheet's global stats footer
        # became an era: its release-type cell ("1352 Total / 99 Album Track /
        # …") and its badge cell ("⭐ 43 Best Of / 🥇 44 Wanted / …") are both
        # invisible to ERA_STATS_PATTERN, so the digit-leading rule below read
        # them as era names. Measured over the corpus: 22 phantom eras across
        # 19 trackers, 15 of them cards literally named "Untitled Era N", one
        # of them claiming 1,352 versions and holding none.
        if _is_stats_only_cell(text):
            continue
        first_line = text.split("\n")[0].strip()
        # If the first line doesn't start with a digit, it's likely an era name
        if not _NUMERIC_STAT_RE.match(first_line):
            return True
        # Digit-leading era names — see docs/decisions.md::parser.py::digit-leading-era-names
        if not ERA_STATS_PATTERN.search(first_line) and not first_line.replace(" ", "").isdigit():
            return True
    # Every non-empty cell states counts — pure stats row
    return False


# Regex for date-prefixed changelog entries like "22.10.2025 - Big findings"
_DATE_PREFIX_RE = re.compile(
    r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}"
    r"|^\d{4}-\d{1,2}-\d{1,2}"
)

# Pre-compiled patterns used in _parse_song_row and parse_art_tab
_UNFINISHED_RE = re.compile(r"\[?unfinished\]?", re.IGNORECASE)
_COVER_RE = re.compile(r"\bcover\b", re.IGNORECASE)

# Punctuation and whitespace normalization for era matching keys
_PUNCT_STRIP_RE = re.compile(r"[,.:;!?'\"]+")
_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")

# Junk era name filtering patterns
_HANDLE_RE = re.compile(r"@\w+")
_CHANGELOG_SLASH_RE = re.compile(r"^\d{1,2}/\d{1,2}\s*[-\u2013]")


def _looks_like_era_name(text: str) -> bool:
    """Check if text looks like a plausible era name (not an announcement/footer).

    Era names are typically short (1-8 words) like "Rap Hard", "Barter 7",
    "Birds in the Trap". Announcements are long multi-line texts like
    "MASS KENDRICK/KEEM GB THAT INCLUDES: ..."
    Footer labels like "Links" or "Changelog" are also excluded.
    """
    # Multi-line blocks (3+ lines) are almost always announcements
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) >= 3:
        return False

    # Take the first line only
    first_line = lines[0].strip() if lines else text.strip()

    # Empty or whitespace-only → not an era
    if not first_line:
        return False

    # A broken formula is not a name. Without this, "#REF!" becomes a real
    # era and the abbreviated-era-name rule below then absorbs every later
    # era into it.
    if _is_spreadsheet_error(first_line):
        return False

    # Check original text for handles/domains before stripping
    orig_lower = first_line.lower()

    # Person/service + social handle in original: "symex (@symex.b) [vaulted.icu]"
    if _HANDLE_RE.search(first_line):
        # Check original (not stripped) text for handle detection
        orig_words = first_line.split()
        if len(orig_words) <= 4:
            return False

    # Domain names in original text: "vaulted.icu", "pillows.su"
    if re.search(r"\.\w{2,4}\b", orig_lower) and any(
        tld in orig_lower for tld in (".icu", ".su", ".gg", ".com", ".net", ".org", ".io")
    ):
        return False

    # Strip parenthetical suffix for length check
    paren_idx = first_line.find("(")
    if paren_idx > 0:
        first_line = first_line[:paren_idx].strip()

    words = first_line.split()
    # Too long or too many words → announcement
    if len(words) > 10 or len(first_line) > 80:
        return False
    # Ends with colon → announcement/label
    if first_line.endswith(":"):
        return False

    lower = first_line.lower()

    # Known non-era labels that appear in the era column
    non_era = {
        "links", "link", "changelog", "changelogs", "notes",
        "tracker guidelines", "guidelines", "discord", "credits",
        "editors", "current editors", "update notes", "resources",
        "template", "template:", "about", "info", "key", "legend",
        "recent additions", "what's new", "what's new?",
        # Meta-labels that aren't music eras
        "types", "type", "owner", "general information", "release date",
        "updates", "mega folder", "performance tracks",
        "progress reports", "rules", "highlighted",
        "current editor", "editor comments",
        # Collaboration/feature labels → should be sections, not eras
        "features", "collaborations", "collaboration", "featured",
        "collaborations & features", "loosies", "guest verses",
        "guest features",
    }
    if lower in non_era:
        return False

    # Starts with "Collaboration with" → section label, not era
    if lower.startswith("collaboration with"):
        return False

    # Contains "tracker" → likely a header/label, not an era
    if "tracker" in lower:
        return False

    # Navigation rows: "Skip to DRILL", "Click to view..."
    if lower.startswith("skip to ") or "click to view" in lower or "click here" in lower:
        return False

    # URLs / discord links → not an era name
    if any(tok in lower for tok in ("discord.gg/", "discord.com/", "http://", "https://", ".gg/")):
        return False

    # Date-prefixed changelog: "22.10.2025 - Big findings", "2024-01-05: ..."
    if _DATE_PREFIX_RE.match(first_line):
        return False

    # Changelog verbs: "Added ...", "Removed ...", "Updated ...", "Renamed ..."
    changelog_verbs = ("added ", "removed ", "updated ", "renamed ", "started ", "finished ")
    if lower.startswith(changelog_verbs):
        return False

    # Pure number or very short numeric: "31", "7", "3" — not an era
    if first_line.isdigit() and len(first_line) <= 3:
        return False

    # Person name + social handle (stripped text): "Fly (@damn4k)"
    # (Primary handle check is above, before paren stripping; this catches
    #  cases where the handle is embedded in the non-paren portion.)
    if _HANDLE_RE.search(first_line) and len(words) <= 3:
        return False

    # Short date-slash changelog: "1/23 - Sent all links", "11/21 - All eras in"
    if _CHANGELOG_SLASH_RE.match(first_line):
        return False

    # Streaming/playlist references: "Spotify playlist for every..."
    if "playlist" in lower or "spotify" in lower:
        return False

    # Exclamation-heavy announcements: "NEW FINDINGS!!!"
    if first_line.count("!") >= 2:
        return False

    # Asterisk-prefixed labels: "*New* Unreleased Guidelines"
    if lower.startswith("*"):
        return False

    # "sent all" / "onlyfiles" patterns in changelogs
    if "sent all" in lower or "onlyfiles" in lower:
        return False

    # Era stats pattern masquerading as era name: "718 Total Full", "3 Leaks"
    if ERA_STATS_PATTERN.match(first_line):
        return False

    return len(words) >= 1


def _is_section_separator(row: list[_Cell]) -> bool:
    """Check if a row is a section separator (e.g. 'Features', 'Collaborations').

    Usually a row where most cells are empty and one or two contain a
    separator keyword. Also matches 'Collaboration with X' patterns.
    """
    non_empty = [c for c in row if c.text.strip()]
    if len(non_empty) <= 2:
        for cell in non_empty:
            cell_lower = cell.text.strip().lower()
            if cell_lower in SECTION_SEPARATORS:
                return True
            # "Collaboration with X" → treat as section
            if cell_lower.startswith("collaboration with"):
                return True
            # Slash-compound labels: "Snippets/Unavailable" → check each part
            parts = cell_lower.split("/")
            if len(parts) >= 2 and all(p.strip() in SECTION_SEPARATORS for p in parts):
                return True
    return False


def _is_section_label_version(
    version: "SongVersion", row: list[_Cell], era_col: int
) -> bool:
    """Return True if this parsed version is structurally a section/sub-era label.

    Some trackers place sub-era labels (e.g. "Full", "Pre-VMA",
    "Watch The Throne – EP", "Before Rick Rubin") as rows that have the era
    name in the era column and only the label text in the name column, with
    nothing else filled in.  These look like songs to _parse_song_row but
    should become named sections inside the current era.

    Detection is structural (no keyword list needed):
    - No song-specific data: no links, no quality/date metadata, no credits
    - Only the era cell + the label cell are non-empty in the row
    """
    if version.links:
        return False
    if version.quality or version.track_length or version.file_date:
        return False
    if version.leak_date or version.available_length:
        return False
    if version.featuring or version.producers or version.collaboration:
        return False
    # Substantive notes → real song entry (e.g. "Unknown date, rumoured leak")
    if version.notes and len(version.notes.strip()) > 20:
        return False
    # Count non-era cells with text; a section label row has only one (the label)
    non_era_filled = sum(
        1 for i, c in enumerate(row)
        if i != era_col and c.text.strip()
    )
    return non_era_filled <= 1


def _is_dynamic_section_label(row: list[_Cell], col_map: dict[str, int]) -> str | None:
    """Detect section labels structurally: 1-2 non-empty cells, short text, no links/data.

    Returns the label text if this row looks like a section label, or None.
    Catches novel section labels that aren't in SECTION_SEPARATORS.
    """
    non_empty = [(i, c) for i, c in enumerate(row) if c.text.strip()]
    if not (1 <= len(non_empty) <= 2):
        return None
    # The text cell must be a short label — either single-line, or a short
    # first line whose remaining lines are all 'note: …' annotations
    # (Carti official: 'Full LQs\nnote: check the remasters tab…').
    text_cell = max(non_empty, key=lambda x: len(x[1].text.strip()))
    label = text_cell[1].text.strip()
    if "\n" in label:
        first, *rest = (ln.strip() for ln in label.split("\n"))
        if not all(re.match(r"^\(?note\b[:\s]", ln, re.IGNORECASE) for ln in rest if ln):
            return None
        label = first
    if len(label) > 60:
        return None
    # Must not have links (would be a song row)
    if any(c.links for _, c in non_empty):
        return None
    # Must not be in data columns (quality, track_length, etc.)
    data_cols = {col_map.get(k) for k in ("quality", "track_length", "available_length", "links")} - {None}
    if text_cell[0] in data_cols:
        return None
    return label


def _is_empty_row(row: list[_Cell]) -> bool:
    """Check if all cells in a row are empty."""
    return all(not c.text.strip() for c in row)


def _is_collab_stub_match(stub_name: str, other_name: str) -> bool:
    """Return True if stub_name is 'Collaboration with X' and other_name ends with 'Collab'.

    Handles the pattern where an era header uses the full collaboration name
    ('Collaboration with TrapMoneyBenny') but song rows use an abbreviated form
    ('TMB Collab').
    """
    if not stub_name.lower().startswith("collaboration with "):
        return False
    if not other_name.lower().rstrip().endswith("collab"):
        return False
    return True


def _era_names_are_related(name_a: str, name_b: str) -> bool:
    """Check if two era name strings likely refer to the same era.

    Used to decide whether a 0-song stub era (built from a name-column header
    row) should be merged into an adjacent songs-bearing era with a similar
    but abbreviated name.  Handles:
      - "Birds In The Trap Sing McKnight" ↔ "Birds"  (prefix match)
      - "Utopia [Phase 1]"               ↔ "Utopia [P1]"  (same first word)
    """
    key_a = _era_match_key(name_a)
    key_b = _era_match_key(name_b)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    # One is a strict prefix of the other (e.g. "birds " in "birds in the trap...")
    if key_a.startswith(key_b + " ") or key_b.startswith(key_a + " "):
        return True
    # Same first significant word (e.g. "utopia" in "utopia [phase 1]" ↔ "utopia [p1]")
    words_a = key_a.split()
    words_b = key_b.split()
    first_a = words_a[0] if words_a else ""
    first_b = words_b[0] if words_b else ""
    return bool(first_a and first_b and first_a == first_b and len(first_a) > 3)


def _transfer_era_metadata(source: Era, target: Era) -> None:
    """Transfer metadata from source era to target era (only fills missing fields)."""
    if source.description and not target.description:
        target.description = source.description
    if source.art_url and not target.art_url:
        target.art_url = source.art_url
    if source.timeline and not target.timeline:
        target.timeline = source.timeline
    if source.stats_raw and not target.stats_raw:
        target.stats_raw = source.stats_raw
        target.stats = source.stats
    # Merge alt_names
    for alt in source.alt_names:
        if alt not in target.alt_names:
            target.alt_names.append(alt)
    # Prefer the longer/fuller name
    if source.name and len(source.name) > len(target.name):
        target.name = source.name


def _merge_empty_stub_eras(eras: list[Era]) -> list[Era]:
    """Merge 0-song stub eras into adjacent songs-bearing eras, transferring metadata.

    Some trackers (e.g. Travis Scott 2.0) place era metadata (name, description,
    year range) in stand-alone name-column rows.  The actual songs use abbreviated
    era names so the stub era ends up with 0 songs.  This step merges the stub's
    metadata into the following songs-bearing era when their names are related,
    preferring the longer/fuller era name from the stub.
    """
    if not eras:
        return eras
    result: list[Era] = []
    i = 0
    while i < len(eras):
        era = eras[i]
        era_songs = sum(len(s.songs) for s in era.sections)
        if era_songs == 0 and i + 1 < len(eras):
            next_era = eras[i + 1]
            next_songs = sum(len(s.songs) for s in next_era.sections)
            if next_songs > 0 and (
                _era_names_are_related(era.name, next_era.name)
                or _is_collab_stub_match(era.name, next_era.name)
            ):
                _transfer_era_metadata(era, next_era)
                # Skip this empty stub
                i += 1
                continue
        result.append(era)
        i += 1

    # Second pass: merge version-tagged empty eras into ANY era with matching base name.
    # e.g. "HiTunes [V3]" (0 songs) → merge into "HiTunes" (has songs).
    remaining_empty = [e for e in result if sum(len(s.songs) for s in e.sections) == 0]
    merged_away: set[int] = set()
    for empty_era in remaining_empty:
        base_key = _era_match_key(empty_era.name)
        if not base_key:
            continue
        for target in result:
            if target is empty_era:
                continue
            target_key = _era_match_key(target.name)
            target_songs = sum(len(s.songs) for s in target.sections)
            if target_key == base_key and target_songs > 0:
                _transfer_era_metadata(empty_era, target)
                merged_away.add(id(empty_era))
                break
    if merged_away:
        result = [e for e in result if id(e) not in merged_away]

    return result


def _consolidate_group_labels(era: Era) -> None:
    """Convert 0-song non-standard sections into group labels for following sections.

    Some trackers use a nested structure where an era has a top-level label
    (e.g. 'Die Lit 2', 'Kanye West - Donda') that acts as a group header for
    the standard sub-sections (Surfaced, Features, OG Files, etc.) beneath it.
    The parser creates these as flat sections with 0 songs.  This function:
      1. Identifies 0-song non-standard sections as group labels.
      2. Propagates the group name to all following sections until the next label.
      3. Removes those group-label placeholder sections from the list.
      4. Removes empty standard sections (e.g. 'Unsurfaced' with 0 songs).
      5. Removes unnamed sections with 0 songs (default section placeholders).
    """
    sections = era.sections
    if len(sections) <= 1:
        return

    current_group: str | None = None
    result: list[Section] = []

    for sec in sections:
        sec_name_lower = sec.name.lower().strip()

        if not sec.name and not sec.songs:
            # Unnamed empty placeholder — skip.
            continue

        if sec.name and not sec.songs:
            if sec_name_lower not in SECTION_SEPARATORS:
                # Non-standard named section with 0 songs → group label.
                current_group = sec.name
                continue  # Folded into group attribute; not kept as a section.
            else:
                # Standard section (Surfaced, Unavailable, etc.) with 0 songs → drop.
                continue

        sec.group = current_group
        result.append(sec)

    era.sections = result


# Keywords that identify the tracker footer section (global stats, changelogs, guidelines).
# Once we hit one of these, we stop parsing songs.
_FOOTER_KEYWORDS = {
    "total links", "total link", "total full",
    "changelogs", "changelog",
    "tracker guidelines", "unreleased guidelines",
    "current tracker editors", "editor comments",
    "current editors",
    "progress reports",
    "want to contribute",
    "update notes", "spreadsheet data",
    "guide & information", "link & invites",
    "whole spreadsheet data",
    "availability summary",
    "other trackers",
    "trackerhub",
    "file hosting",
}


# Single alternation scan beats checking every keyword separately per cell
_FOOTER_KEYWORDS_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_FOOTER_KEYWORDS, key=len, reverse=True))
)


def _is_tracker_footer(row: list[_Cell]) -> bool:
    """Check if a row belongs to the tracker footer (stats, changelogs, guidelines).

    This prevents footer content from being attributed to the last era.
    """
    for cell in row:
        if cell.text and _FOOTER_KEYWORDS_RE.search(cell.text.lower()):
            return True
    return False


def _normalize_unicode(text: str) -> str:
    """Normalize Unicode text by replacing diacritics with their base characters.

    Handles cases like "geëky" → "geeky", "ROSALÍA" → "ROSALIA".
    """
    # NFKD decomposition splits characters like ë into e + combining diaeresis
    decomposed = unicodedata.normalize("NFKD", text)
    # Remove combining characters (diacritics)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _era_match_key(full_era_name: str, *, keep_discriminators: bool = False) -> str:
    """Extract the matching key from an era name, lowercased for matching.

    *keep_discriminators* preserves the two things that tell sibling eras apart:
    a ``[V1]``/``[V2]`` version tag and a parenthetical like ``(2018)``. Song
    rows reference their era without either, so the default drops both — but an
    Art tab names each one's cover explicitly ("Donda [V2]", "Good Ass Job
    (2018)"), and collapsing those onto one key handed every sibling the first
    one's artwork. See docs/decisions.md::parser.py::art-version-keys.

    Era headers contain full names like "Before Baby Keem(as Hykeem Carter...)"
    but song rows only use "Before Baby Keem".  We extract the text before
    the first '(' that is directly glued to the previous word (no space),
    strip any version tags [V1]/[V2], and lowercase for case-insensitive matching.

    Examples:
    - "Before Baby Keem(as Hykeem Carter...)" → "before baby keem"
    - "Ca$ino(Child With Wolves, Janice)" → "ca$ino"  (matches "CA$INO")
    - "Tu Pimp A Caterpillar [V1](...)" → "tu pimp a caterpillar"
    - "THC: The High Chronical$" → "thc: the high chronical$"
    - "(Mollyworld, Balaclava Era)" → "mollyworld, balaclava era"
    - "Super geëky" → "super geeky"  (diacritics normalized)
    """
    key = full_era_name
    if not keep_discriminators:
        # Strip from first '(' onward
        paren_idx = key.find("(")
        if paren_idx > 0:
            key = key[:paren_idx]
        elif paren_idx == 0:
            # Entire name is parenthetical — use content inside parens
            close = key.find(")")
            if close > 0:
                key = key[1:close]
    key = key.strip()
    # Strip version tags like [V1], [V2], [V3]
    if not keep_discriminators:
        key = VERSION_TAG_PATTERN.sub("", key).strip()
    # Strip trailing asterisk used by some trackers (e.g. Travis Scott) to
    # denote the "features/collabs within this era" sub-section.  We want
    # "Rodeo*" to resolve to the same "Rodeo" era as non-asterisk rows.
    key = key.rstrip("*").strip()
    # Normalize Unicode diacritics (ë→e, á→a, etc.)
    key = _normalize_unicode(key)
    key = key.lower()
    # Strip punctuation (commas, periods, colons, etc.) so
    # "Meet The Woo, Vol. 2" matches "Meet The Woo Vol 2" and
    # "AT.LONG.LAST.A$AP" matches "AT LONG LAST A$AP".
    key = _PUNCT_STRIP_RE.sub(" ", key)
    key = _WHITESPACE_COLLAPSE_RE.sub(" ", key).strip()
    return key


def _song_match_key(name: str) -> str:
    """Stable normalized song identity key for cross-era version linkage.

    Same normalization recipe as era keys (diacritics, case, version tags,
    punctuation, whitespace) applied to a song base name, so "THIS ONE HERE"
    in WAR and "This One Here" in DONDA 2 share one key. Exposed to clients
    as ``Song.song_key``.
    """
    key = _normalize_unicode(name)
    key = VERSION_TAG_PATTERN.sub("", key)
    key = key.lower()
    key = _PUNCT_STRIP_RE.sub(" ", key)
    key = _WHITESPACE_COLLAPSE_RE.sub(" ", key).strip()
    return key


def _fuzzy_era_match(key: str, era_by_key: dict[str, Era]) -> Era | None:
    """Fuzzy match a row's era key against known era keys.

    Uses word-overlap scoring. Requires at least 2 shared significant
    words (length > 2) and >= 50% overlap with the smaller word set.

    Handles cases like "Digital Nas Collab" matching
    "Collaboration with Digital Nas".
    """
    key_words = _significant_words(key)
    if not key_words:
        return None

    best_match: Era | None = None
    best_score = 0.0

    for era_key, era in era_by_key.items():
        era_words = _significant_words(era_key)
        if not era_words:
            continue
        overlap = len(key_words & era_words)
        min_size = min(len(key_words), len(era_words))
        score = overlap / min_size if min_size > 0 else 0
        if score > best_score and overlap >= 2:
            best_score = score
            best_match = era

    if best_score >= 0.5 and best_match is not None:
        return best_match

    # Acronym matching: if key matches the acronym of a known era.
    # e.g. "sftsaftm" → "Shoot For The Stars Aim For The Moon"
    key_clean = key.replace(" ", "")
    if len(key_clean) >= 3:
        for era_key, era in era_by_key.items():
            if _acronym(era_key) == key_clean:
                return era

    return None


# Both helpers are called once per era key PER UNMATCHED ROW — a 100-era
# tracker registers ~300 keys, and Ye is 9350 rows, so the uncached form built
# millions of sets. The key strings repeat across rows, which is exactly what
# an lru_cache wants.
@lru_cache(maxsize=8192)
def _significant_words(era_key: str) -> frozenset[str]:
    """Words long enough to carry meaning in overlap scoring."""
    return frozenset(w for w in era_key.split() if len(w) > 2)


@lru_cache(maxsize=8192)
def _acronym(era_key: str) -> str:
    """First letters of a >=3-word key ("shoot for the stars" → "sfts")."""
    words = era_key.split()
    if len(words) < 3:
        return ""
    return "".join(w[0] for w in words if w)


# ---------------------------------------------------------------------------
# Link cleanup
# ---------------------------------------------------------------------------

def _clean_link(url: str) -> str:
    """Strip Google redirect wrapper from URLs.

    Google Sheets wraps links as: https://www.google.com/url?q=REAL_URL&...
    """
    if "google.com/url" in url:
        try:
            qs = parse_qs(urlparse(url).query)
        except ValueError:
            return url
        target = qs.get("q")
        if target and target[0]:
            return target[0]
    return url


def _extract_links_from_cell(cell: _Cell) -> list[str]:
    """Get cleaned links from a cell."""
    return [_clean_link(link) for link in cell.links if link]


def _register_era_keys(
    era: Era,
    era_name: str,
    era_by_key: dict[str, Era],
    fallback_keys: dict[str, Era] | None = None,
) -> None:
    """Register all matching keys for an era (primary, full, alt-names, slash parts).

    Primary, full, and alt-name keys are written to ``era_by_key`` with
    setdefault semantics (earlier authoritative registrations win).

    Slash-separated parts ("38 Baby / Ay Ay" → "38 baby", "ay ay") are written
    to ``fallback_keys`` when provided so they only resolve a row era when no
    primary registration matches — preventing a partial-name from shadowing a
    genuine standalone era declared later in the tracker. If ``fallback_keys``
    is None, slash parts fall back to the same ``era_by_key`` dict (legacy).
    """
    primary = _era_match_key(era_name)
    if primary:
        era_by_key.setdefault(primary, era)
    full = _normalize_unicode(era_name).lower().strip()
    if full and full != primary:
        era_by_key.setdefault(full, era)
    # Alt names
    for alt in era.alt_names:
        alt_key = _era_match_key(alt)
        if alt_key:
            era_by_key.setdefault(alt_key, era)
        # Comma alias list → fallback dict — see docs/decisions.md::parser.py::era-key-shadowing
        parts = _split_alt_aliases(alt)
        if len(parts) > 1:
            target = fallback_keys if fallback_keys is not None else era_by_key
            for part in parts:
                part_key = _era_match_key(part)
                if part_key:
                    target.setdefault(part_key, era)
    # Slash-separated: "38 Baby / Ay Ay" → register both parts
    if " / " in era_name:
        target = fallback_keys if fallback_keys is not None else era_by_key
        for part in era_name.split(" / "):
            part_key = _era_match_key(part)
            if part_key:
                target.setdefault(part_key, era)


# ---------------------------------------------------------------------------
# High-level parser
# ---------------------------------------------------------------------------

def _has_song_data(v: SongVersion) -> bool:
    """Return True if the version has at least one song-like metadata field."""
    return bool(
        v.links or v.quality or v.track_length
        or v.available_length or v.leak_date or v.file_date
    )


def _era_own_keys(era: Era) -> set[str]:
    """Every key form this era's own header/aliases can be referenced by.

    Used by the positional-exact prior: a row value matching ANY of these
    belongs to this era when it is the current header, regardless of which
    sibling era registered the shared key first in the global dicts.
    """
    keys: set[str] = set()
    primary = _era_match_key(era.name)
    if primary:
        keys.add(primary)
    full = _normalize_unicode(era.name).lower().strip()
    if full:
        keys.add(full)
    for alt in era.alt_names:
        alt_key = _era_match_key(alt)
        if alt_key:
            keys.add(alt_key)
        for part in _split_alt_aliases(alt):
            part_key = _era_match_key(part)
            if part_key:
                keys.add(part_key)
    if " / " in era.name:
        for part in era.name.split(" / "):
            part_key = _era_match_key(part)
            if part_key:
                keys.add(part_key)
    return keys


def _get_cell_text(row: list[_Cell], idx: int) -> str:
    """Safely get cell text by index, returning empty string if out of range."""
    if 0 <= idx < len(row):
        return row[idx].text.strip()
    return ""


def _get_cell(row: list[_Cell], idx: int) -> _Cell:
    """Safely get a _Cell by index."""
    if 0 <= idx < len(row):
        return row[idx]
    return _Cell()


def _detect_header_row(rows: list[list[_Cell]]) -> tuple[int, dict[str, int]]:
    """Scan rows to find the header row and return its index and column map.

    Some trackers have a title/instruction row before the actual column
    headers (e.g. "Avicii Leaks by Azyy" in row 0, actual headers in row 2).
    Searches up to ``_MAX_HEADER_SCAN_ROWS`` rows for one that yields at least
    2 canonical column detections.

    Returns:
        ``(header_row_idx, col_map)`` — the index of the header row and the
        detected column mapping.
    """
    col_map = detect_columns(rows[0])
    if len(col_map) >= 2:
        return 0, col_map
    for try_idx in range(1, min(_MAX_HEADER_SCAN_ROWS, len(rows))):
        candidate_map = detect_columns(rows[try_idx])
        if len(candidate_map) >= 2:
            return try_idx, candidate_map
    return 0, col_map


def _first_row_image(row: list[_Cell], prefer_idx: int | None = None) -> str | None:
    """First image URL found in *row* — the cover-art candidate for an
    auto-created era.

    With *prefer_idx*, that cell's image wins before the left-to-right scan
    (Travis-style headers embed the art in the name cell). Previously this
    scan was copy-pasted at three call sites.
    """
    if prefer_idx is not None:
        cell = _get_cell(row, prefer_idx)
        if cell.images:
            return cell.images[0]
    for idx, cell in enumerate(row):
        if idx == prefer_idx:
            continue
        if cell.images:
            return cell.images[0]
    return None


def _parse_era_header_row(
    row: list[_Cell], col_map: dict[str, int]
) -> tuple[Era, bool]:
    """Extract era data from a recognised era-header row.

    Args:
        row: The table row classified as an era header.
        col_map: Column index mapping produced by ``detect_columns()``.

    Returns:
        ``(era, needs_backfill)`` where *era* is the constructed :class:`Era`
        and *needs_backfill* is ``True`` when the name cell contained only an
        image with no usable text (the real name must be filled in from the
        first subsequent song row).
    """
    era_name_col = col_map.get("name", 1)
    notes_col = col_map.get("notes", 2)

    era_name_full = _get_cell_text(row, era_name_col)
    timeline_raw = _get_cell_text(row, notes_col)
    era_stats_raw = _get_cell_text(row, 0)

    # Extract era art, highlighted producers, and description from trailing cells.
    art_url = None
    highlighted_producers: list[str] = []
    desc_candidates: list[str] = []

    # Image-only era name vs. album art — see docs/decisions.md::parser.py::name-cell-image
    name_cell = _get_cell(row, era_name_col)
    name_text = name_cell.text.strip()
    name_has_usable_text = bool(
        name_text
        and not (name_text.startswith("(") and name_text.endswith(")"))
    )
    if name_cell.images and name_has_usable_text:
        art_url = name_cell.images[0]

    for i, cell in enumerate(row):
        if i <= notes_col:
            continue  # skip stats, name, timeline columns
        if cell.images and not art_url:
            art_url = cell.images[0]
        text = cell.text.strip()
        if text:
            if "Highlighted" in text and "Producer" in text:
                highlighted_producers = parse_highlighted_producers(text)
            else:
                desc_candidates.append(text)

    era_desc = max(desc_candidates, key=len) if desc_candidates else None
    timeline = parse_timeline(timeline_raw) if timeline_raw else []
    era_stats = parse_era_stats(era_stats_raw) if era_stats_raw else None

    # Split main name from alt names (newline-separated, alts in parens)
    name_lines = era_name_full.split("\n") if era_name_full else [""]
    era_name = name_lines[0].strip()
    alt_names: list[str] = []
    for _line in name_lines[1:]:
        _line = _line.strip()
        if _line.startswith("(") and _line.endswith(")"):
            _line = _line[1:-1].strip()
        if _line:
            alt_names.append(_line)

    # Detect image-based era names: the name cell has an image but no usable
    # text (empty, or purely parenthetical like "(Mollyworld, Balaclava Era)").
    # The real name will be backfilled from the first song row's era column.
    needs_backfill = False
    if not era_name or (era_name.startswith("(") and era_name.endswith(")")):
        if era_name.startswith("(") and era_name.endswith(")"):
            inner = era_name[1:-1].strip()
            if inner and inner not in alt_names:
                alt_names.insert(0, inner)
            era_name = ""
        needs_backfill = True

    era = Era(
        name=era_name,
        alt_names=alt_names,
        description=era_desc if era_desc else None,
        timeline=timeline,
        stats_raw=era_stats_raw if era_stats_raw else None,
        stats=era_stats,
        art_url=art_url,
        highlighted_producers=highlighted_producers,
        sections=[Section()],  # default unnamed section
    )
    return era, needs_backfill


# Column labels that mark an artwork tab. These tabs DO have Era/Name/Notes
# columns, so they parse cleanly as song tabs and emit one "song" per cover —
# 19 of them on the Harry Styles tracker. Two or more hits is deliberately
# conservative: a single "Image" column also appears on physical-release tabs,
# which are genuine song content.
_ARTWORK_COLUMN_SIGNS = frozenset({
    "art type", "project type", "designer", "cover art", "image type",
    "cover type", "photo type", "use", "used", "used?", "made by", "image",
})
_MIN_ARTWORK_SIGNS = 2

# Signatures that identify a tab outright. One hit is enough: no song tab has
# an "Interviewer(s)" or "Time Signature" column.
_INTERVIEW_COLUMN_SIGNS = frozenset({
    "interview title", "interview type", "interviewer", "interviewers",
    "interviewer(s)",
})
_MUSICOLOGY_COLUMN_SIGNS = frozenset({"bpm", "key", "time signature"})
_MIN_MUSICOLOGY_SIGNS = 2

# The glossary tab every template ships: "Portion | <description> | Quality |
# <description>", defining what Snippet/Tagged/Lossless mean. It resolves to
# exactly these two columns and nothing else, and yields one "song" per legend
# entry. This is a statement about the WHOLE resolved header, not a missing
# column — a headerless song tab resolves to an empty map and is unaffected,
# and any tab with an era, name, link, length or date column is unaffected too.
_GLOSSARY_COLUMNS = frozenset({"available_length", "quality"})


def is_song_tab(header_row: list[_Cell], col_map: dict[str, int]) -> bool:
    """Return False for tabs that hold something other than songs.

    Trackers keep glossaries, artwork indexes, interview logs, setlists and
    BPM/key references as ordinary tabs. Run through the song parser these do
    not fail — they emit plausible-looking junk. The Car Seat Headrest
    interview tab produced 146 "songs" whose titles were interview headlines,
    because no Name column was detected and `name` fell back to positional
    index 1, which happened to be "Interview Title".

    Rejection is only ever on a POSITIVE signature — never on the absence of a
    column. Two rounds of measurement proved absence is not evidence:

      * "no Name column" destroyed De La Soul (205 songs under an unlabelled
        header cell) and Overlord's Lil Uzi Vert discography (283 songs under
        "Project & Track Title", which no alias covers).
      * "neither Name nor Era" then destroyed tabs with no header row at all —
        BIG L (21 songs) and Labrinth (169) start at row 0 with data, so
        detect_columns returns an empty map and the positional fallback
        (name=1, notes=2) is what correctly parses them.

    The one col_map-based rule is also positive evidence, about the whole
    resolved header rather than a missing piece of it: a header that resolves
    to exactly {available_length, quality} and nothing else is the glossary tab
    every template ships. Both counter-examples above resolve to an empty map
    or to a much wider one, so neither is touched.
    """
    labels = {
        " ".join(c.text.split()).strip().lower().rstrip(":").strip('"')
        for c in header_row
    }
    if len(labels & _ARTWORK_COLUMN_SIGNS) >= _MIN_ARTWORK_SIGNS:
        return False
    if labels & _INTERVIEW_COLUMN_SIGNS:
        return False
    if len(labels & _MUSICOLOGY_COLUMN_SIGNS) >= _MIN_MUSICOLOGY_SIGNS:
        return False
    return not (col_map and set(col_map) <= _GLOSSARY_COLUMNS)


def _absolutize_era_art(eras: list[Era], source_url: str) -> None:
    """Resolve relative cover-art URLs against the tab they came from.

    Google's htmlview export always emits absolute image URLs, so this is a
    no-op there. Self-hosted trackers (deftonestracker.net, franktracker.net,
    tylertracker.net) emit "/assets/<sha>.jpg", which reached clients verbatim
    and could be fetched by nothing — 268 eras across the captured corpus.
    """
    for era in eras:
        if era.art_url and not urlparse(era.art_url).netloc:
            era.art_url = urljoin(source_url, era.art_url)


def parse_sheet(
    html_content: str, artist_name: str, source_url: str | None = None
) -> Artist:
    """Parse a Google Sheets HTML export into an Artist model.

    This is the main entry point for parsing a single tracker.

    *source_url* is the URL the HTML came from, used to resolve relative image
    sources. Optional so callers parsing a local file keep working; without it
    relative URLs pass through unchanged, exactly as before.
    """
    # Extract cell background colors from the stylesheet (non-neutral only)
    rows = extract_table(html_content)
    if not rows:
        # An empty ParseMetadata, not None: this was the one return path that
        # left it unset, so every consumer had to special-case a tab with no
        # table. Zeroes state the truth — nothing was read — and keep the
        # row-accounting identity holding on every path.
        return Artist(
            name=artist_name,
            slug=slugify(artist_name),
            eras=[],
            parse_metadata=ParseMetadata(),
        )

    # Step 1: detect column layout from header row.
    header_row_idx, col_map = _detect_header_row(rows)

    # Step 1a: refuse tabs that are not song tabs. Parsing a glossary or an
    # artwork index yields junk that looks exactly like data — see is_song_tab.
    if not is_song_tab(rows[header_row_idx], col_map):
        return Artist(
            name=artist_name,
            slug=slugify(artist_name),
            eras=[],
            parse_metadata=ParseMetadata(
                total_rows=len(rows) - header_row_idx - 1,
                other_rows=len(rows) - header_row_idx - 1,
                dropped_columns=detect_dropped_columns(rows[header_row_idx], col_map)[0],
            ),
        )

    # Some tabs carry no era header rows at all: the Era column simply repeats
    # a value on every song row. Without a header row to anchor them, the
    # abbreviated-era rule below ("plausible era name + real song data => stay
    # in the current era") swallows every new value, and the whole tab collapses
    # into one era named after whatever appeared first. Measured on the
    # OsamaSon tracker: 8 distinct era values, all 81 songs filed under one.
    #
    # When a tab has no era headers, the Era column is the only era signal there
    # is, so it becomes authoritative. Tabs that DO have header rows keep the
    # abbreviation heuristic, which exists for sheets that shorten the era name
    # on song rows.
    flat_era_mode = not any(_is_era_header(r) for r in rows[header_row_idx + 1:])

    # Step 1b: extract announcement notices from header cells and pre-header rows.
    pre_header_rows = rows[:header_row_idx] if header_row_idx > 0 else []
    notices = _extract_header_notices(rows[header_row_idx], pre_header_rows, artist_name)

    # Step 2: walk rows, classify and extract
    eras: list[Era] = []
    current_era: Era | None = None
    # Map from lowercased era matching key → Era object.
    # Keys are lowercase, parenthetical-stripped, version-tag-stripped.
    era_by_key: dict[str, Era] = {}
    # Fallback registrations (currently: slash-split parts). Consulted only
    # when the primary dict has no match — so a genuine "Ay Ay" era declared
    # later still wins over a "38 Baby / Ay Ay" partial registration.
    era_by_key_fallback: dict[str, Era] = {}
    # Eras whose name cell had an image but no usable text — backfill from
    # the first song row's era column.
    _needs_name_backfill: set[int] = set()  # id(era) values
    # id(era) → its own key forms, for the positional-exact prior.
    _era_own_keys_cache: dict[int, set[str]] = {}
    # (id(era), song base name) → Song, for O(1) version grouping
    song_index: dict[tuple[int, str], Song] = {}
    in_footer = False

    # Parse metadata tracking
    total_rows = len(rows) - 1 - header_row_idx  # exclude header and pre-header rows
    song_rows = 0
    skipped_rows = 0
    unmatched_rows: list[str] = []
    unmatched_total = 0
    footer_rows = 0
    fuzzy_matched_rows = 0

    for row_idx, row in enumerate(rows):
        # Skip header row and any rows before it (title/instruction rows)
        if row_idx <= header_row_idx:
            continue

        # Skip empty rows
        if _is_empty_row(row):
            continue

        # Meta banner between the header and the first era (Travis Scott:
        # '| Last Updated: … | Hover over the headers … |') → notice.
        if current_era is None:
            filled = [c for c in row if c.text.strip()]
            if (
                len(filled) == 1
                and not filled[0].links
                and re.search(
                    r"last updated|hover over|how to use", filled[0].text, re.IGNORECASE
                )
            ):
                text = filled[0].text.strip().strip("|").strip()
                # Dedupe against header notices and repeated banner rows —
                # _extract_header_notices has its own seen-set, but this
                # append site bypasses it.
                if text.lower() not in {n.text.lower() for n in notices}:
                    notices.append(Notice(text=text, link=None, kind="info"))
                continue

        # Era header is checked FIRST — before the separator and footer
        # checks, both of which would otherwise swallow it. Matching one also
        # resets footer state. Why: docs/decisions.md.
        if _is_era_header(row):
            in_footer = False
            current_era, needs_backfill = _parse_era_header_row(row, col_map)
            eras.append(current_era)
            _register_era_keys(current_era, current_era.name, era_by_key, era_by_key_fallback)
            if needs_backfill:
                _needs_name_backfill.add(id(current_era))
            continue

        # Section separators → capture as named sections within current era
        if _is_section_separator(row):
            if current_era is not None:
                non_empty = [c for c in row if c.text.strip()]
                label = non_empty[0].text.strip() if non_empty else ""
                if label:
                    current_era.sections.append(Section(name=label))
            continue

        # Check name column for footer signals (e.g. "CARTI TRACKER HUB").
        name_col_text = _get_cell_text(row, col_map.get("name", 1)).strip().lower()
        if name_col_text in _NAME_FOOTER_KEYWORDS:
            in_footer = True
            footer_rows += 1
            continue

        # Footer detection: flag instead of break.
        # If a new era header appears after footer content, in_footer resets above.
        if _is_tracker_footer(row):
            in_footer = True
            footer_rows += 1
            continue

        if in_footer:
            footer_rows += 1
            continue

        # Check for song row: first cell should match a known era key
        era_col = col_map.get("era", 0)
        row_era = _get_cell_text(row, era_col)

        # Backfill-era priority — see docs/decisions.md::parser.py::backfill-era-priority
        if (
            row_era
            and current_era is not None
            and id(current_era) in _needs_name_backfill
        ):
            current_era.name = row_era
            _register_era_keys(current_era, row_era, era_by_key, era_by_key_fallback)
            _needs_name_backfill.discard(id(current_era))
            version = _parse_song_row(row, col_map)
            if version:
                _add_version_to_era(current_era, version, song_index)
                song_rows += 1
            continue

        if row_era:
            row_era_norm = _normalize_unicode(row_era).lower()
            row_era_stripped = _era_match_key(row_era)

            # Positional-exact prior: a value naming the era we are
            # currently under belongs there, ahead of any sibling that
            # registered a shared key first. Why: docs/decisions.md.
            matched_era = None
            if current_era is not None:
                own_keys = _era_own_keys_cache.get(id(current_era))
                if own_keys is None:
                    own_keys = _era_own_keys(current_era)
                    _era_own_keys_cache[id(current_era)] = own_keys
                if row_era_norm in own_keys or row_era_stripped in own_keys:
                    matched_era = current_era

            # Case-insensitive exact lookup with Unicode normalization
            if matched_era is None:
                matched_era = era_by_key.get(row_era_norm)

            # Try stripped key (version tags removed) if exact fails
            if matched_era is None and row_era_stripped != row_era_norm:
                matched_era = era_by_key.get(row_era_stripped)

            # Fallback dict (slash parts) — only consulted after primary fails,
            # so a real era declared later still wins over a partial registration.
            if matched_era is None:
                matched_era = era_by_key_fallback.get(row_era_norm)
                if matched_era is None and row_era_stripped != row_era_norm:
                    matched_era = era_by_key_fallback.get(row_era_stripped)

            # Fuzzy positional prior, ahead of the global fuzzy search: a
            # value that fuzzy-matches the current header is an abbreviation
            # of it, and a similarly-worded sibling would outscore it.
            # Why: docs/decisions.md.
            if matched_era is None and current_era is not None:
                cur_key = _era_match_key(current_era.name) if current_era.name else ""
                if cur_key and _fuzzy_era_match(row_era_norm, {cur_key: current_era}):
                    matched_era = current_era
                    fuzzy_matched_rows += 1
                    # Future rows with the same abbreviation resolve exactly
                    # (fallback tier, so a genuine era keeps primary-key wins).
                    era_by_key_fallback.setdefault(row_era_stripped, current_era)
                    logger.debug(
                        "Positional fuzzy match: %r → current era %r",
                        row_era_norm, current_era.name,
                    )

            # Fuzzy match if all exact paths fail
            if matched_era is None:
                matched_era = _fuzzy_era_match(row_era_norm, era_by_key)
                if matched_era is not None:
                    fuzzy_matched_rows += 1
                    logger.debug(
                        "Fuzzy era match: %r → %r", row_era_norm, matched_era.name
                    )

            if matched_era is not None:
                current_era = matched_era
                version = _parse_song_row(row, col_map)
                if version:
                    if _is_section_label_version(version, row, era_col):
                        current_era.sections.append(Section(name=version.name))
                    else:
                        _add_version_to_era(current_era, version, song_index)
                        song_rows += 1
                continue

            # No matching era found in era_by_key (exact or fuzzy).
            # Two paths depending on whether we already have a current_era.
            if current_era is not None:
                # There IS a current era from a previous header/auto-creation.
                # Check if this row's era name is the same as current era (case-insensitive).
                # If yes → assign. If different → auto-create a new era.
                current_key = _era_match_key(current_era.name) if current_era.name else ""
                row_key = _era_match_key(row_era)
                if current_key and row_key == current_key:
                    # Same era (abbreviated or exact) — assign to current
                    version = _parse_song_row(row, col_map)
                    if version:
                        _add_version_to_era(current_era, version, song_index)
                        song_rows += 1
                    else:
                        non_empty = [c for c in row if c.text.strip()]
                        if len(non_empty) <= 3 and row_era:
                            current_era.sections.append(Section(name=row_era))
                    continue
                else:
                    # Different era name — auto-create a new era if plausible,
                    # but prefer positional assignment when the row has real song data
                    # and the era name doesn't look like a distinct album/era.
                    version = _parse_song_row(row, col_map)
                    if version and _looks_like_era_name(row_era):
                        # Abbreviated era names on song rows — see
                        # docs/decisions.md::parser.py::abbreviated-era-names.
                        # Suppressed in flat_era_mode: with no header rows in
                        # the tab, a new Era-column value is a new era, not an
                        # abbreviation of the current one.
                        if _has_song_data(version) and not flat_era_mode:
                            _add_version_to_era(current_era, version, song_index)
                            song_rows += 1
                            era_by_key_fallback.setdefault(_era_match_key(row_era), current_era)
                        else:
                            new_era = Era(name=row_era, sections=[Section()])
                            eras.append(new_era)
                            _register_era_keys(new_era, row_era, era_by_key, era_by_key_fallback)
                            current_era = new_era
                            # Auto-created eras keep the row's own song —
                            # dropping it here was silent data loss.
                            # Why: docs/decisions.md.
                            _add_version_to_era(current_era, version, song_index)
                            song_rows += 1
                    elif version:
                        # Not a plausible era name but has song data —
                        # assign to current era as fallback
                        _add_version_to_era(current_era, version, song_index)
                        song_rows += 1
                    else:
                        # No song data — could be a sub-era section header
                        # or a stats-less era header. Use heuristic: if very
                        # few cells are filled, it's a section of current era.
                        non_empty = sum(1 for c in row if c.text.strip())
                        if non_empty <= 2 or not _looks_like_era_name(row_era):
                            current_era.sections.append(Section(name=row_era))
                        else:
                            # Enough data to be an era header without stats
                            notes_idx = col_map.get("notes", 2)
                            name_idx = col_map.get("name", 1)
                            timeline_raw = _get_cell_text(row, notes_idx) or _get_cell_text(row, name_idx)
                            timeline = parse_timeline(timeline_raw) if timeline_raw else []
                            new_era = Era(name=row_era, timeline=timeline, art_url=_first_row_image(row), sections=[Section()])
                            eras.append(new_era)
                            _register_era_keys(new_era, row_era, era_by_key, era_by_key_fallback)
                            current_era = new_era
                    continue
            else:
                # No current era at all — auto-create from this row.
                # Handles trackers with no era headers (Young Thug, etc.)
                if not _looks_like_era_name(row_era):
                    # Skip non-era rows (announcements, footers, etc.)
                    skipped_rows += 1
                    unmatched_total += 1
                    if len(unmatched_rows) < _MAX_UNMATCHED_ROWS:
                        row_text = " | ".join(c.text.strip() for c in row if c.text.strip())[:200]
                        if row_text:
                            unmatched_rows.append(f"Row {row_idx}: {row_text}")
                    continue

                version = _parse_song_row(row, col_map)
                if version:
                    new_era = Era(name=row_era, sections=[Section()])
                    eras.append(new_era)
                    _register_era_keys(new_era, row_era, era_by_key, era_by_key_fallback)
                    current_era = new_era
                    _add_version_to_era(current_era, version, song_index)
                    song_rows += 1
                else:
                    # No song data — stats-less era header (Kid Cudi style)
                    notes_idx = col_map.get("notes", 2)
                    name_idx = col_map.get("name", 1)
                    timeline_raw = _get_cell_text(row, notes_idx) or _get_cell_text(row, name_idx)
                    timeline = parse_timeline(timeline_raw) if timeline_raw else []
                    new_era = Era(name=row_era, timeline=timeline, art_url=_first_row_image(row), sections=[Section()])
                    eras.append(new_era)
                    _register_era_keys(new_era, row_era, era_by_key)
                    current_era = new_era
                continue

        # Sub-era header vs. section label — see docs/decisions.md::parser.py::sub-era-header
        name_col_idx = col_map.get("name", 1)
        name_val = _get_cell_text(row, name_col_idx)
        if name_val:
            # Split multi-line name cells (e.g. "The Graduates\n(2007 - 2009)")
            # and use only the first line as the era display name.
            name_first_line = name_val.split("\n")[0].strip()
            # A \n means a <br>-separated second line (year range) — reliable
            # signal that this row is a stats-less era header, not a section.
            has_multiline_name = "\n" in name_val
            non_empty = sum(1 for c in row if c.text.strip())
            if non_empty <= 3:
                if has_multiline_name and _looks_like_era_name(name_first_line):
                    # Stats-less era header with multi-line name (Travis style).
                    # Create a new era, capture description, and scan for art image.
                    notes_idx = col_map.get("notes", 2)
                    desc_text = _get_cell_text(row, notes_idx)
                    _era_art_url = _first_row_image(row, prefer_idx=name_col_idx)
                    new_era = Era(
                        name=name_first_line,
                        art_url=_era_art_url,
                        description=desc_text or None,
                        sections=[Section()],
                    )
                    eras.append(new_era)
                    # Register full name_val so _era_match_key strips the
                    # parenthetical year and matches e.g. "The Graduates"
                    _register_era_keys(new_era, name_val, era_by_key)
                    current_era = new_era
                elif current_era is not None:
                    # Single-line section label (e.g. "Other Media",
                    # "OG / Uncut Files") — add as a named section to the
                    # current era and let later song rows auto-create if needed.
                    current_era.sections.append(Section(name=name_first_line))
                    # Section-label-as-alias — see docs/decisions.md::parser.py::section-label-alias
                    _register_era_keys(current_era, name_first_line, era_by_key_fallback)
                else:
                    # No current era — create one from the name column.
                    # This handles Yung Lean style trackers.
                    new_era = Era(name=name_first_line, sections=[Section()])
                    eras.append(new_era)
                    _register_era_keys(new_era, name_val, era_by_key)
                    current_era = new_era
                continue

        # Fallback: check if any non-era cell has short single-line text
        # that could be a section label (e.g. Carti's "WLR Higher Bitrate Files"
        # in the Notes column with empty Era and Name).
        if current_era is not None and not row_era and not name_val:
            # Timeline continuation row: the era header's timeline column
            # spills into a following row holding only '(date) - event' text
            # (Carti official: '(December 25, 2020 - March, 2021) - …').
            filled = [c.text.strip() for c in row if c.text.strip()]
            if len(filled) == 1 and filled[0].startswith("("):
                spill_events = parse_timeline(filled[0])
                if spill_events:
                    current_era.timeline = list(current_era.timeline or []) + spill_events
                    continue

            dyn_label = _is_dynamic_section_label(row, col_map)
            if dyn_label:
                current_era.sections.append(Section(name=dyn_label))
                continue

        # Positional fallback — see docs/decisions.md::parser.py::positional-fallback
        if not row_era and current_era is not None:
            version = _parse_song_row(row, col_map)
            if version and (version.name or _has_song_data(version)):
                _add_version_to_era(current_era, version, song_index)
                song_rows += 1
                continue

        # Unmatched row — track it for diagnostics
        skipped_rows += 1
        unmatched_total += 1
        if len(unmatched_rows) < _MAX_UNMATCHED_ROWS:
            row_text = " | ".join(c.text.strip() for c in row if c.text.strip())[:200]
            if row_text:
                unmatched_rows.append(f"Row {row_idx}: {row_text}")

    # Step 3: detect and parse global stats row
    tracker_stats = _find_global_stats(rows)

    # Merge 0-song stub eras — see docs/decisions.md::parser.py::merge-stub-eras
    eras = _merge_empty_stub_eras(eras)

    if source_url:
        _absolutize_era_art(eras, source_url)

    # Step 3c: consolidate group labels within each era's sections
    for era in eras:
        _consolidate_group_labels(era)
        _sort_era_versions(era)

    # Step 4: build parse metadata
    unknown_columns, duplicate_columns = detect_dropped_columns(
        rows[header_row_idx], col_map
    )
    metadata = ParseMetadata(
        total_rows=total_rows,
        song_rows=song_rows,
        skipped_rows=skipped_rows,
        unmatched_rows=unmatched_rows,
        unmatched_rows_total=unmatched_total,
        footer_rows=footer_rows,
        other_rows=max(0, total_rows - song_rows - skipped_rows - footer_rows),
        fuzzy_matched_rows=fuzzy_matched_rows,
        dropped_columns=unknown_columns,
        duplicate_columns=duplicate_columns,
    )

    logger.debug(
        "Parsed %r: %d eras, %d song rows, %d skipped, %d fuzzy-matched era rows",
        artist_name,
        len(eras),
        song_rows,
        skipped_rows,
        fuzzy_matched_rows,
    )
    if unmatched_rows:
        logger.warning(
            "Parser found %d unmatched rows in %r (showing first %d): %s",
            len(unmatched_rows),
            artist_name,
            min(5, len(unmatched_rows)),
            " | ".join(unmatched_rows[:5]),
        )

    return Artist(
        name=artist_name,
        slug=slugify(artist_name),
        eras=_disambiguate_era_names(eras),
        tracker_stats=tracker_stats,
        parse_metadata=metadata,
        notices=notices,
    )


def _disambiguate_era_names(eras: list[Era]) -> list[Era]:
    """Guarantee every era in a tracker has a distinct, non-empty name.

    Era name is the identity key every client uses — iOS derives `Era.id` and
    every `EraRow.id` from it, and SwiftUI silently keeps only the FIRST row
    per duplicate id. Two eras sharing a name, or several with none at all,
    therefore made whole era cards vanish: across the cached corpus that hid
    69 cards and 1,662 versions, all of it present in the payload and counted
    in the stats bar. It also collides the expand/collapse state, which is
    keyed by the same string.

    Renaming here rather than client-side fixes every client at once, and
    fixes the lookup keys as well as the ids.
    """
    seen: dict[str, int] = {}
    out: list[Era] = []
    for i, era in enumerate(eras, start=1):
        name = (era.name or "").strip() or f"Untitled Era {i}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        if count > 1:
            name = f"{name} ({count})"
            seen[name] = 1  # so a real "Foo (2)" later doesn't collide either
        out.append(era.model_copy(update={"name": name}) if name != era.name else era)
    return out


def _find_global_stats(rows: list[list[_Cell]]) -> TrackerStats | None:
    """Scan rows for the global tracker stats row and parse it.

    The global stats row is typically near the bottom and contains
    "Total Links" or "Total Full" in its cells. The row has 4 data cells:
      - Links stats
      - Quality stats
      - Availability stats
      - Highlighted/badge stats

    Different trackers place these in different column indices due to
    colspan differences, so we extract by content matching.
    """
    for row in reversed(rows):
        # Look for the signature "Total Links" or "Total Full"
        cell_texts = [c.text for c in row]
        has_links = any("Total Links" in t or "Total Link" in t for t in cell_texts)
        has_avail = any("Total Full" in t for t in cell_texts)

        if has_links or has_avail:
            links_text = ""
            quality_text = ""
            availability_text = ""
            highlights_text = ""

            for cell in row:
                t = cell.text
                if "Total Links" in t or "Total Link" in t or "Missing Links" in t:
                    links_text = t
                elif "Lossless" in t or "CD Quality" in t:
                    quality_text = t
                elif "Total Full" in t or "OG Files" in t or "OG File" in t:
                    availability_text = t
                elif "Best Of" in t or "Special" in t or "Grails" in t:
                    highlights_text = t

            return parse_tracker_stats(links_text, quality_text, availability_text, highlights_text)

    return None


# Compound availability grammar (Travis Scott tracker — no Quality column):
# '<avail> - HQ', 'Unconfirmed (Snippet - LQ)', 'Full - HQ (Unofficial)\n⭐⭐⭐⭐☆'.
_COMPOUND_QUALITY_PATTERN = re.compile(r"\s*-\s*(~?)(HQ|LQ|CDQ)\b")
# Stars may be separated by whitespace, including newlines — a sheet that puts
# each star on its own line renders as "⭐\n⭐\n⭐\n⭐". A bare `[⭐★]+` run stops
# at the first separator, so it stripped one star and left the rest glued to
# the availability value. The rating is the count of star glyphs in the run.
_STAR_RATING_PATTERN = re.compile(r"\s*([⭐★][\s⭐★☆]*)\s*$")
_STAR_GLYPH_RE = re.compile(r"[⭐★]")
_COMPOUND_QUALITY_NAMES = {
    "HQ": "High Quality", "LQ": "Low Quality", "CDQ": "CD Quality",
}

# U+FE0F selects emoji presentation and is invisible. Sheets emit "⭐️" (U+2B50
# U+FE0F) as often as bare "⭐", and the selector between two stars broke the
# `[⭐★]+` run, so the pattern matched nothing at all. Effect measured over
# 23,695 real versions before this fix: zero carried a rating, and the stars
# stayed glued onto the availability value, corrupting that field too.
_VARIATION_SELECTORS = str.maketrans("", "", "️︎")


def _split_compound_availability(text: str) -> tuple[str, str | None, int | None]:
    """Split a compound availability value into (availability, quality, rating).

    Only used when the tracker has no dedicated Quality column. Returns the
    input unchanged (with None quality/rating) when no marker is present.
    """
    text = text.translate(_VARIATION_SELECTORS)
    rating = None
    m = _STAR_RATING_PATTERN.search(text)
    if m:
        rating = min(len(_STAR_GLYPH_RE.findall(m.group(1))), 5)
        text = text[: m.start()].rstrip()

    quality = None
    qm = _COMPOUND_QUALITY_PATTERN.search(text)
    if qm:
        quality = _COMPOUND_QUALITY_NAMES[qm.group(2)]
        text = (text[: qm.start()] + text[qm.end():])
        # Collapse artifacts left by the removal: '()' and stray whitespace
        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"[ \t]+", " ", text.replace("\n", " ")).strip()

    return text, quality, rating


def _parse_song_row(row: list[_Cell], col_map: dict[str, int]) -> SongVersion | None:
    """Parse a song data row into a SongVersion."""
    name_idx = col_map.get("name", 1)
    raw_name = _get_cell_text(row, name_idx)

    if not raw_name:
        return None

    # Extract badge emoji
    badge, after_badge = extract_badge(raw_name)

    # Parse credits and alt titles from the multi-line name
    credits = parse_song_credits(after_badge)
    title = credits.title
    featuring = credits.featuring
    producers = credits.producers
    collaboration = credits.collaboration
    refs = credits.refs
    alt_titles = credits.alt_titles

    # Check for "(unfinished)" or "[unfinished]" in alt_titles or title.
    # These are status tags, not alternative names — remove from alt_titles
    # and promote to version_tag (overriding only if no tag was found yet).
    _found_unfinished = any(_UNFINISHED_RE.fullmatch(t.strip()) for t in alt_titles)
    if _found_unfinished:
        alt_titles = [t for t in alt_titles if not _UNFINISHED_RE.fullmatch(t.strip())]

    # Extract version tag from the clean title
    version_tag, _base = extract_version_tag(title)
    # Use base name (tag stripped) to avoid duplication in the UI
    title = _base

    # If found unfinished tag but no explicit version tag, set one
    if _found_unfinished and not version_tag:
        version_tag = "Unfinished"

    # Build the version object
    notes_idx = col_map.get("notes", 2)
    notes_cell = _get_cell(row, notes_idx)
    notes_text = notes_cell.text.strip() if notes_cell.text else None

    # Extract structured metadata from notes, then strip the extracted OG
    # lines so clients don't render the filenames twice (structured field +
    # raw notes text).
    og_filenames = extract_og_filenames(notes_text) if notes_text else []
    samples = extract_samples(notes_text) if notes_text else []
    if og_filenames and notes_text:
        notes_text = strip_og_filename_lines(notes_text) or None

    # Dedicated File Name / Instrumental Name column: same concept as the
    # 'OG Filename:' notes convention — column values lead, notes-derived
    # names follow, no duplicates. Why: docs/decisions.md.
    og_col_text = _get_cell_text(row, col_map.get("og_filename_col", -1))
    if og_col_text:
        col_names = [ln.strip() for ln in og_col_text.split("\n") if ln.strip()]
        og_filenames = col_names + [n for n in og_filenames if n not in col_names]

    # Dedicated credit columns: a Producer column fills producers only when
    # the inline '(prod. …)' didn't; Artist/Credited Artist columns carry the
    # row's performer, which is NOT a feature. Why: docs/decisions.md.
    if not producers:
        producers = _get_cell_text(row, col_map.get("producers_col", -1)) or None
    credited_artists = _get_cell_text(row, col_map.get("credited_artists", -1)) or None

    links_idx = col_map.get("links")
    alt_links_idx = col_map.get("alt_links")
    link_cell = _get_cell(row, links_idx) if links_idx is not None else _Cell()
    alt_link_cell = _get_cell(row, alt_links_idx) if alt_links_idx is not None else _Cell()

    # Sources column (Travis Scott tracker): labeled evidence links, kept
    # separate from listen links. Each URL pairs with the text line it sits
    # on (same link_lines mechanism the notice extractor uses).
    sources: list[SourceRef] = []
    sources_idx = col_map.get("sources")
    if sources_idx is not None:
        src_cell = _get_cell(row, sources_idx)
        src_lines = src_cell.text.split("\n")
        for link_idx, link in enumerate(src_cell.links):
            cleaned = _clean_link(link)
            if not cleaned:
                continue
            line_num = (
                src_cell.link_lines[link_idx]
                if link_idx < len(src_cell.link_lines)
                else -1
            )
            label = src_lines[line_num].strip() if 0 <= line_num < len(src_lines) else ""
            sources.append(SourceRef(label=label, url=cleaned))
    # Collect links from the dedicated links cell, alternate links cell, and the notes cell,
    # merging them while preserving order and removing duplicates.
    all_links = _extract_links_from_cell(link_cell) + _extract_links_from_cell(alt_link_cell)
    note_links = _extract_links_from_cell(notes_cell)
    seen: set[str] = set()
    merged_links: list[str] = []
    for lnk in all_links + note_links:
        if lnk not in seen:
            seen.add(lnk)
            merged_links.append(lnk)

    avail_text = _get_cell_text(row, col_map.get("available_length", -1))
    quality_text = _get_cell_text(row, col_map.get("quality", -1))
    streaming_text = _get_cell_text(row, col_map.get("streaming", -1)).strip().lower()
    streaming = {"yes": True, "no": False}.get(streaming_text)
    rating = None
    if avail_text and "quality" not in col_map:
        # Travis-style trackers fold quality (and a fan star rating) into the
        # availability cell: 'Full - HQ (Unofficial)\n⭐⭐⭐⭐☆'.
        avail_text, split_quality, rating = _split_compound_availability(avail_text)
        quality_text = split_quality or ""

    version = SongVersion(
        name=title,
        version_tag=version_tag,
        badge=badge,
        featuring=featuring,
        producers=producers,
        credited_artists=credited_artists,
        collaboration=collaboration,
        refs=refs,
        director=credits.director,
        alt_titles=alt_titles,
        notes=notes_text,
        og_filename=og_filenames[0] if og_filenames else None,
        og_filenames=og_filenames,
        samples=samples,
        sources=sources,
        track_length=_get_cell_text(row, col_map.get("track_length", -1)) or None,
        file_date=_get_cell_text(row, col_map.get("file_date", -1)) or None,
        leak_date=_get_cell_text(row, col_map.get("leak_date", -1)) or None,
        available_length=avail_text or None,
        quality=quality_text or None,
        streaming=streaming,
        rating=rating,
        links=merged_links,
        date_of_recording=_get_cell_text(row, col_map.get("date_of_recording", -1)) or None,
        preview_date=_get_cell_text(row, col_map.get("preview_date", -1)) or None,
        type=_get_cell_text(row, col_map.get("type", -1)) or None,
    )

    return version


# Base names that mark an UNKNOWN song rather than a shared title. Rows with
# these names are distinct mystery tracks (different notes/dates/samples) and
# must never be grouped as versions of one song.
_PLACEHOLDER_BASE_NAMES = frozenset({"???", "??", "?", "unknown", "untitled", "tba", "n/a"})


def _sort_era_versions(era: Era) -> None:
    """Order every song's versions by tag family, then number, then sheet order.

    Versions arrived in spreadsheet row order, which is not the order anyone
    reads them in: [Demo 10] landed next to [Demo 1], and a song's V-takes
    were interleaved with its demos. The sort is stable, so untagged and
    unrecognised versions keep their original relative position at the end.
    """
    for section in era.sections:
        for song in section.songs:
            if len(song.versions) < 2:
                continue
            # enumerate first: the sheet index has to come from the position,
            # not from a lookup on the list being sorted.
            song.versions = [
                v
                for _, v in sorted(
                    enumerate(song.versions),
                    key=lambda pair: version_sort_key(pair[1].version_tag, pair[0]),
                )
            ]


def _add_version_to_era(
    era: Era,
    version: SongVersion,
    song_index: dict[tuple[int, str], Song],
) -> None:
    """Add a version to the appropriate Song in the era, creating it if needed.

    Songs with the same base name (ignoring version tags [V1], [V2], etc.) are
    grouped together — even across sections. New songs are added to the last
    (current) section. ``song_index`` maps (id(era), base_name) → Song so the
    grouping lookup is O(1) instead of scanning every song in the era.

    Placeholder names ("???", "Unknown", …) mark songs the fanbase can't
    identify by title. When such a row carries a fan-made alt title, that alt
    title is the song's identity — rows sharing it group together. Without an
    alt title each row is its own standalone Song (distinct mystery tracks).
    """
    if not era.sections:
        era.sections.append(Section())

    _, base_name = extract_version_tag(version.name)
    # Also strip any sub-info in parens for grouping
    # But keep the base_name as-is for matching — only strip version tags
    base_key = base_name.strip()

    if base_key.lower() in _PLACEHOLDER_BASE_NAMES:
        alts = [a.strip().lower() for a in (version.alt_titles or []) if a.strip()]
        if not alts:
            # No fan-made identity — song_key stays empty (no cross-era link).
            era.sections[-1].songs.append(Song(base_name=base_key, versions=[version]))
            return
        # Group by fan-made alt title instead of the placeholder name. Any
        # shared alt title joins the group — a row listing several alts
        # bridges renames (e.g. '???. Bon Iver' later known as 'Time2Time').
        alt_keys = [(id(era), f"alt::{a}") for a in alts]
        song = next((song_index[k] for k in alt_keys if k in song_index), None)
        if song is None:
            song = Song(
                base_name=base_key,
                song_key=_song_match_key(alts[0]),
                versions=[version],
            )
            era.sections[-1].songs.append(song)
        else:
            song.versions.append(version)
        for k in alt_keys:
            song_index.setdefault(k, song)
        return

    key = (id(era), base_key)
    song = song_index.get(key)
    if song is not None:
        song.versions.append(version)
        return

    # Create new song in the last (current) section
    song = Song(
        base_name=base_key,
        song_key=_song_match_key(base_key),
        versions=[version],
    )
    era.sections[-1].songs.append(song)
    song_index[key] = song


# ---------------------------------------------------------------------------
# Badge tabs — Best Of / Worst Of / Special / Grails / Wanted annotate songs
# ---------------------------------------------------------------------------

_BADGE_BY_TAB_KIND = {
    "best_of": Badge.BEST,
    "worst_of": Badge.WORST,
    "special": Badge.SPECIAL,
    "grails": Badge.GRAIL,
    "wanted": Badge.WANTED,
}

# Separator-row labels inside a highlight tab map to the same badges as the
# tab kinds do — see BADGE_SECTION_LABELS in parse_misc_tab.
_BADGE_BY_SECTION_LABEL = {
    "grails": Badge.GRAIL,
    "grail": Badge.GRAIL,
    "wanted": Badge.WANTED,
    "best of": Badge.BEST,
    "worst of": Badge.WORST,
    "special": Badge.SPECIAL,
    "notable": Badge.SPECIAL,
}


def _badge_for_entry(entry: MiscEntry, tab_default: Badge) -> Badge:
    """Resolve one highlight-tab row's badge.

    28 of 415 trackers ship a combined "Grails / Wanted" tab, which
    classifies as kind ``grails``. Its rows carry their own signal: each is
    emoji-prefixed (🏆 grail vs 🏅/🥇/🥉 wanted) and the two blocks are
    introduced by a "Grails" / "Wanted" separator row. Row emoji wins, then
    the section label, then the tab's own kind.
    """
    badge, _ = extract_badge(entry.name)
    if badge is not None:
        return badge
    labelled = _BADGE_BY_SECTION_LABEL.get(entry.section.strip().lower())
    if labelled is not None:
        return labelled
    return tab_default


def apply_badge_tabs(
    artist: Artist, tabs: list[tuple[str, list[MiscEntry]]]
) -> int:
    """Stamp badges from every highlight tab onto matching main-tab songs.

    Builds the song index ONCE for all tabs (a Ye-size artist can carry up
    to five badge tabs). Matches era-scoped first (normalized era + song
    keys), then falls back to a name-only match when the song key is unique
    across the tracker. Placeholder tracks ("???", "untitled", …) are never
    badge targets, and songs that already carry any badge (inline emoji from
    the main tab) are left untouched. Returns the number of songs annotated.

    Both sides of the match drop their leading badge emoji first: highlight
    tabs routinely prefix every row ("🏆 Snaily [V2]"), and that emoji is
    part of the raw name, so keying on it matched nothing at all.
    """
    if not any(_BADGE_BY_TAB_KIND.get(kind) for kind, _ in tabs):
        return 0

    by_era_and_name: dict[tuple[str, str], Song] = {}
    by_name: dict[str, list[Song]] = {}
    for era in artist.eras:
        era_key = _era_match_key(era.name)
        for section in era.sections:
            for song in section.songs:
                _, song_name = extract_badge(song.base_name)
                if song_name.strip().lower() in _PLACEHOLDER_BASE_NAMES:
                    continue
                song_key = _song_match_key(song_name)
                if not song_key:
                    continue
                by_era_and_name.setdefault((era_key, song_key), song)
                by_name.setdefault(song_key, []).append(song)

    applied = 0
    for kind, entries in tabs:
        tab_default = _BADGE_BY_TAB_KIND.get(kind)
        if tab_default is None:
            continue
        for entry in entries:
            _, entry_name = extract_badge(entry.name)
            _, base_name = extract_version_tag(entry_name)
            song_key = _song_match_key(base_name)
            if not song_key:
                continue
            song = by_era_and_name.get((_era_match_key(entry.era_name), song_key))
            if song is None:
                candidates = by_name.get(song_key, [])
                if len(candidates) == 1:
                    song = candidates[0]
            if song is None or not song.versions:
                continue
            if any(v.badge is not None for v in song.versions):
                continue
            song.versions[0].badge = _badge_for_entry(entry, tab_default)
            applied += 1
    return applied


# ---------------------------------------------------------------------------
# Misc / Music Videos tab parsing — secondary tabs, kept separate from eras
# ---------------------------------------------------------------------------

# Local alias map — deliberately separate from COLUMN_ALIASES so these tabs'
# quirks ("Media Length", "Streaming") never perturb main-tab detection.
_MISC_COLUMN_ALIASES = {
    "era": "era",
    # Carti's Released tab has BOTH "Rel. Era" and "Rec. Era"; the first
    # era-mapped column in header order wins (release era — it leads on the
    # sheet), the second is ignored by the `not in candidate` guard below.
    "rel. era": "era",
    "rec. era": "era",
    "name": "name",
    "title": "name",  # Stems tabs (Travis) use "Title"
    "notes": "notes",
    "length": "length",
    "media length": "length",
    "track length": "length",
    "date": "date",
    "release date": "date",
    "leak date": "date",  # Best Of / Worst Of / Stems tabs
    "type": "entry_type",
    "available": "available",
    "available length": "available",
    "currently available": "available",
    "quality": "quality",
    "streaming": "streaming",
    "links": "links",
    "link(s)": "links",
    "link": "links",
    "sources": "links",  # Travis Stems' link column
    # Deliberately unmapped (no MiscEntry field, dropped): BPM, Key
    # (Ye/Kendrick Stems), Made By/Creator (Fakes).
}

# Highlight-block labels that appear as lone-cell separator rows inside a
# badge tab. A combined "Grails / Wanted" tab uses them to divide its halves.
BADGE_SECTION_LABELS = frozenset({
    "grails", "grail", "wanted", "best of", "worst of", "special", "notable",
})

# Era header rows in these tabs carry per-era stats in the era column,
# e.g. "3 Released 0 Unreleased 0 BTS 0 On Streaming".
_MISC_ERA_STATS_RE = re.compile(
    r"\d+\s+(?:Released|Unreleased|BTS|On\s+Streaming|Full|Snippet)", re.IGNORECASE
)

# Shape-based stats cell match — see docs/decisions.md::parser.py::STATS_LIKE_ERA_RE
_STATS_LIKE_ERA_RE = re.compile(r"^\s*\d+\s+\S")


def _misc_header_key(text: str) -> str:
    key = text.strip()
    paren = key.find("(")
    if paren > 0:
        key = key[:paren]
    # "Link(s)" — the paren is part of the name, keep a special case
    if text.strip().lower().startswith("link"):
        key = "links"
    # Colon-suffixed headers ("Era:", "Type:") — same grammar the 2026-07-20
    # sweep found on main tabs; strip like detect_columns does.
    return re.sub(r"\s+", " ", key.strip().lower()).rstrip(":").strip()


# A date cell is short and carries a digit. Era-header rows on some Misc tabs
# put the era DESCRIPTION in the column that maps to `date`, which made the
# header look like it carried track data, so the era-header guard below never
# fired and the era was emitted as an entry whose "date" was a paragraph — 37
# of them on the Ye tracker's Misc tab, each rendering a wall of prose beside a
# calendar icon in the app.
_MAX_DATE_LEN = 40


def _looks_like_date(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    return len(stripped) <= _MAX_DATE_LEN and any(c.isdigit() for c in stripped)


def parse_misc_tab(
    html: str, kind: str, artist_eras: Iterable[str] = ()
) -> list[MiscEntry]:
    """Parse a Misc or Music Videos tab HTML export into MiscEntry rows.

    ``kind`` is ``"misc"`` or ``"music_videos"`` and is stamped on each entry
    as ``source_tab``. ``artist_eras`` are the main tab's era names, used to
    recognise header rows — a tab's own era column often abbreviates them
    ("Birds" where the header reads "Birds In The Trap Sing McKnight"), so
    the column alone can't spot every header. Rows keep the literal era label from their era column
    (or the last era header); no fuzzy matching against main-tab eras.
    """
    rows = extract_table(html)
    if not rows:
        return []

    # Find the header row: needs at least era+name (or name+links) matches.
    col_map: dict[str, int] = {}
    header_idx = -1
    for idx, row in enumerate(rows[: _MAX_HEADER_SCAN_ROWS]):
        candidate: dict[str, int] = {}
        for c_idx, cell in enumerate(row):
            key = _misc_header_key(cell.text)
            canonical = _MISC_COLUMN_ALIASES.get(key)
            if canonical and canonical not in candidate:
                candidate[canonical] = c_idx
        # A name column plus any second content signal qualifies — "date"
        # covers Stems layouts that have neither an Era nor a Links header.
        if "name" in candidate and (
            "era" in candidate or "links" in candidate or "date" in candidate
        ):
            col_map = candidate
            header_idx = idx
            break
    if header_idx < 0:
        return []

    def cell_text(row: list[_Cell], field: str) -> str:
        idx = col_map.get(field, -1)
        if idx < 0 or idx >= len(row):
            return ""
        return row[idx].text.strip()

    # Every value the era column actually uses. Lets the loop below recognise
    # the empty-era-cell header style without a keyword list: a title naming
    # one of these is a header for rows that follow it.
    era_col = col_map.get("era", -1)
    known_eras: set[str] = {k for k in map(_era_match_key, artist_eras) if k}
    if era_col >= 0:
        for row in rows[header_idx + 1:]:
            if era_col < len(row):
                key = _era_match_key(row[era_col].text.split("\n")[0].strip())
                if key:
                    known_eras.add(key)

    entries: list[MiscEntry] = []
    current_era = ""
    current_section = ""
    # Only highlight tabs carry block separators; elsewhere a lone "Special"
    # cell is an entry, not a label.
    is_badge_tab = kind in _BADGE_BY_TAB_KIND

    for row in rows[header_idx + 1:]:
        if all(not c.text.strip() for c in row):
            continue

        era_text = cell_text(row, "era")
        name = cell_text(row, "name")

        # Grails/Wanted section separator — see docs/decisions.md::parser.py::grails-wanted-separator
        lone = [c.text.strip() for c in row if c.text.strip()]
        if is_badge_tab and len(lone) == 1:
            _, label = extract_badge(lone[0])
            if label.lower() in BADGE_SECTION_LABELS:
                current_section = label
                continue

        # Era header row: stats text in the era column, era name in the name
        # column (mirrors the main tab's grammar).
        if era_text and _MISC_ERA_STATS_RE.search(era_text):
            if name:
                current_era = name.split("\n")[0].strip()
            continue
        if not name:
            continue

        first_line = name.split("\n")[0].strip()
        name_key = _era_match_key(first_line)
        era_key = _era_match_key(era_text.split("\n")[0].strip()) if era_text else ""

        if era_text:
            current_era = era_text.split("\n")[0].strip()

        # Links: prefer parsed <a href> targets, fall back to URL-ish text.
        links: list[str] = []
        links_idx = col_map.get("links", -1)
        if 0 <= links_idx < len(row):
            cell = row[links_idx]
            links.extend(_clean_link(l) for l in cell.links)
            if not links:
                text = cell.text.strip()
                if text.startswith(("http://", "https://")):
                    links.append(text)
        links = [l for l in links if l]

        streaming_text = cell_text(row, "streaming").lower()
        streaming = {"yes": True, "no": False}.get(streaming_text)

        def opt(field: str) -> str | None:
            val = cell_text(row, field)
            if field == "date" and not _looks_like_date(val):
                return None
            return val or None

        entry = MiscEntry(
            era_name=current_era,
            section=current_section,
            name=first_line,
            notes=opt("notes"),
            entry_type=opt("entry_type"),
            date=opt("date"),
            length=opt("length"),
            available=opt("available"),
            quality=opt("quality"),
            streaming=streaming,
            links=links,
            source_tab=kind,
        )
        # Structural-row detection — see docs/decisions.md::parser.py::badge-tab-structural-rows
        has_track_data = any((
            entry.date, entry.length,
            entry.available, entry.quality, entry.links,
        )) or entry.streaming is not None

        # Two more era-header shapes — see docs/decisions.md::parser.py::badge-tab-structural-rows
        stats_era = bool(_STATS_LIKE_ERA_RE.match(era_text))
        if name_key and name_key in known_eras and name_key != era_key:
            if stats_era or (not era_text and not has_track_data):
                current_era = first_line
                continue

        if not has_track_data:
            # Bare label rows — see docs/decisions.md::parser.py::badge-tab-structural-rows
            if not entry.notes and not entry.entry_type:
                continue
            # A known divider keyword with no track data is a label even when
            # it carries an aside — Travis's "Project" rows explain how
            # features are credited.
            if first_line.lower() in SECTION_SEPARATORS:
                continue

        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Art tab parsing — high-quality era artwork
# ---------------------------------------------------------------------------

# Art-tab header labels. The tab has its own layout (no Name/Links columns),
# so it gets its own tiny header detection rather than COLUMN_ALIASES.
_ART_ERA_HEADERS = frozenset({"era", "album", "project", "era/project"})
# Ordered best-first, NOT a set: an art tab can carry both an "Art Type" column
# (the medium — Digital / Scan / Photo) and a "Project Type" column (the role —
# Front Cover / Booklet / Promo Art). Only the role column can identify a cover,
# and on the Ye tab the medium column comes first, so first-match-wins bound
# type_idx to it and the cover preference below never fired for a single era —
# every era silently fell back to whichever artwork was listed first.
# See docs/decisions.md::parser.py::art-type-column-priority.
_ART_TYPE_HEADERS = ("project type", "type", "image type", "category", "art type")


class ArtMap(dict):
    """era match key -> cover URL, remembering which keys are stand-ins.

    A *synthetic* key is a version-stripped alias the parser invents so an era
    spelled without a tag ("Donda") still resolves against an Art tab that
    spells it "Donda [V1]". It names one specific version's cover, so it must
    never serve a DIFFERENT version — see _apply_era_art. A dict subclass
    rather than a second return value: every caller already treats this as a
    plain mapping.
    """

    __slots__ = ("synthetic",)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.synthetic: set[str] = set()


def _art_tab_columns(rows: list[list[_Cell]]) -> tuple[int | None, int | None, int]:
    """Locate the Era and Project Type columns and the first data row.

    Returns ``(era_idx, type_idx, start_row)``. Either index may be None on
    art tabs that have no header row — callers fall back to scanning the
    whole row, which is what this function exists to avoid.
    """
    for idx, row in enumerate(rows[:5]):
        if any(cell.images for cell in row):
            break  # already into the data; no header row above it
        era_idx = type_idx = None
        type_rank = len(_ART_TYPE_HEADERS)
        for c_idx, cell in enumerate(row):
            key = re.sub(r"\s+", " ", cell.text.strip().lower()).rstrip(":").strip()
            if era_idx is None and key in _ART_ERA_HEADERS:
                era_idx = c_idx
            # Best-ranked header wins, not the leftmost one.
            if key in _ART_TYPE_HEADERS:
                rank = _ART_TYPE_HEADERS.index(key)
                if rank < type_rank:
                    type_rank, type_idx = rank, c_idx
        if era_idx is not None or type_idx is not None:
            return era_idx, type_idx, idx + 1
    start = 1 if rows and not any(cell.images for cell in rows[0]) else 0
    return None, None, start


def parse_art_tab(html: str, source_url: str | None = None) -> dict[str, str]:
    """Parse an Art tab HTML export → {era_match_key: image_url} mapping.

    *source_url* resolves relative image sources, exactly as in parse_sheet.
    Absolutising here rather than at the call site matters because
    apply_art_tab_images OVERWRITES era.art_url after parse_sheet has already
    run its own resolution — so an Art tab on a self-hosted tracker would put
    the unusable "/assets/<sha>.jpg" back.

    Art tabs in tracker spreadsheets contain full-resolution era artwork.
    Each row typically has an era name in one cell and one or more images.

    Multiple images may appear per era (front cover, back cover, promo photo,
    background art, etc.).  We prefer images whose **Project Type** column
    says "cover" — e.g. "Front Cover", "Album Cover", "Cover Art".
    If no cover-labelled image is found for an era, we fall back to the first
    available image in the row.

    The cover test reads the Project Type column, not the whole row: tracker
    Notes prose mentions "cover" constantly (626 rows on the Ye art tab), so
    a row-wide match fired almost everywhere and the era's *first* row won.
    See docs/decisions.md::parser.py::art-cover-column.

    Returns a dict keyed by the normalised era match key (lowercase, stripped).
    """
    rows = extract_table(html)
    if not rows:
        return {}

    era_idx, type_idx, start = _art_tab_columns(rows)

    # First pass: collect all images per era key, noting which have cover descriptions.
    # era_info: {era_key: {"cover": url, "first": url}}
    era_info: dict[str, dict[str, str | None]] = {}
    # Version-stripped key → the FIRST versioned key filed under it, so an era
    # the Art tab spells without a version tag still resolves.
    base_keys: dict[str, str] = {}
    # Art tabs leave the era cell blank on an era's continuation rows, so the
    # last seen era carries forward. Without this a blank era cell fell back
    # to the first non-empty cell — the artwork's own name — filing the image
    # under an era that doesn't exist.
    last_era_name = ""

    for row in rows[start:]:
        if not row:
            continue

        # First image found in the row is the candidate
        img_url = next((cell.images[0] for cell in row if cell.images), None)
        if not img_url:
            continue

        if era_idx is not None:
            era_name = _get_cell_text(row, era_idx).strip() or last_era_name
        else:
            # No Era header — fall back to the first non-empty text cell.
            era_name = next((cell.text.strip() for cell in row if cell.text.strip()), "")
        if not era_name:
            continue
        last_era_name = era_name

        # Version-aware: the Art tab lists each version's own cover, so
        # "Donda [V2]" must not collapse onto "Donda [V1]".
        key = _era_match_key(era_name, keep_discriminators=True)
        if not key:
            continue
        base_keys.setdefault(_era_match_key(era_name), key)

        if key not in era_info:
            era_info[key] = {"cover": None, "first": None}

        # Record the first image seen for this era
        if era_info[key]["first"] is None:
            era_info[key]["first"] = img_url

        if type_idx is not None:
            cover_text = _get_cell_text(row, type_idx)
        else:
            cover_text = " ".join(c.text.strip() for c in row if c.text.strip())
        if era_info[key]["cover"] is None and _COVER_RE.search(cover_text):
            era_info[key]["cover"] = img_url

    # Build final map: prefer cover-labelled image, fall back to first image
    result = ArtMap()
    for key, info in era_info.items():
        chosen = info["cover"] or info["first"]
        if chosen:
            if source_url and not urlparse(chosen).netloc:
                chosen = urljoin(source_url, chosen)
            result[key] = chosen

    # Also file each entry under its version-stripped key, so an era named
    # "Donda" still resolves against an Art tab that says "Donda [V1]" (and
    # vice versa). First versioned entry wins, matching the old behaviour.
    # Marked synthetic: the key names one version's cover, and handing it to a
    # sibling version is how "Cruel Winter [V1]" came to show [V2]'s artwork.
    for base, versioned in base_keys.items():
        if base not in result and versioned in result:
            result[base] = result[versioned]
            result.synthetic.add(base)

    return result


def apply_art_tab_images(artist: Artist, art_map: dict[str, str]) -> None:
    """Replace era.art_url with higher-quality Art tab images where available.

    Matches eras by their normalised name key (via _era_match_key) and falls
    back to alt_names when the primary name doesn't match.  Eras with no
    match in art_map are left unchanged.
    """
    for era in artist.eras:
        _apply_era_art(era, art_map)


def _apply_era_art(era: Era, art_map: dict[str, str]) -> None:
    """Give *era* its Art-tab cover, if the tab names one for this version.

    Version-aware key first: "Donda [V2]" has its own cover on the Art tab and
    must not fall through to the version-stripped "donda", which resolves to
    whichever version came first.

    A tagged era may still fall through to the stripped key when the Art tab
    genuinely lists the era without a tag — but a SYNTHETIC stripped key is one
    specific sibling's cover, so for a tagged era it is wrong data. On the Ye
    tracker the Art tab lists only "Cruel Winter [V2]"; the alias made "cruel
    winter" resolve to it, so "Cruel Winter [V1]" was served its sibling's
    cover and lost the correct one the main tab had already given it. 55 such
    aliases across the captured corpus.

    It is still better than a blank card when there is nothing else, so it is
    demoted to a last resort rather than dropped: taken only after every other
    name and key has missed, and only for an era that has no artwork at all.
    """
    synthetic = getattr(art_map, "synthetic", frozenset())
    stand_in: str | None = None
    for name in (era.name, *era.alt_names):
        exact = _era_match_key(name, keep_discriminators=True)
        if exact and exact in art_map:
            era.art_url = art_map[exact]
            return
        stripped = _era_match_key(name)
        if not stripped or stripped not in art_map:
            continue
        if stripped in synthetic and VERSION_TAG_PATTERN.search(name):
            if stand_in is None:
                stand_in = art_map[stripped]
            continue
        era.art_url = art_map[stripped]
        return
    if stand_in is not None and not era.art_url:
        era.art_url = stand_in


# ---------------------------------------------------------------------------
# File-level convenience
# ---------------------------------------------------------------------------

def parse_file(path: Path | str, artist_name: str) -> Artist:
    """Parse a tracker HTML file into an Artist model."""
    path = Path(path)
    try:
        html_content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Some exports arrive cp1252-encoded (smart quotes etc.)
        html_content = path.read_text(encoding="cp1252", errors="replace")
    return parse_sheet(html_content, artist_name)


# ---------------------------------------------------------------------------
# TrackerHub master sheet — the tracker discovery feed
# ---------------------------------------------------------------------------

def _parse_yes_no(text: str) -> bool | None:
    t = text.strip().lower()
    if t.startswith("yes"):
        return True
    if t.startswith("no"):
        return False
    return None


_TRACKER_STAR_CHARS = "\u2b50\ufe0f "  # star + variation selector + space


def parse_trackerhub(html: str) -> list[TrackerEntry]:
    """Parse the TrackerHub sheet into tracker entries.

    Rows: [Trackers (name + link, star prefix = featured), Credits,
    Up To Date?, Working Links?]. Banner/header rows carry no credit and
    no Yes/No flags, which is what filters them out.

    Lives here rather than in the API layer because the fetcher needs it too:
    the hosts of the trackers listed here are what /sheet is allowed to fetch
    (see config.sheet_host_allowed).
    """
    entries: list[TrackerEntry] = []
    for row in extract_table(html):
        if not row:
            continue
        name_cell = row[0]
        raw_name = name_cell.text.strip()
        if not raw_name or not name_cell.links:
            continue
        credit = row[1].text.strip() if len(row) > 1 else ""
        up_to_date = _parse_yes_no(row[2].text) if len(row) > 2 else None
        working_links = _parse_yes_no(row[3].text) if len(row) > 3 else None
        # Banner rows (rules text, discord invites) have a name/link but
        # neither credits nor status flags — real tracker rows always have
        # at least one of them.
        if not credit and up_to_date is None and working_links is None:
            continue
        best = raw_name.startswith("\u2b50")
        name = raw_name.lstrip(_TRACKER_STAR_CHARS).strip()
        if not name:
            continue
        entries.append(TrackerEntry(
            name=name,
            url=_clean_link(name_cell.links[0]),
            credit=credit or None,
            best=best,
            up_to_date=up_to_date,
            working_links=working_links,
        ))
    entries.sort(key=lambda e: (not e.best, e.name.lower()))
    return entries


# ---------------------------------------------------------------------------
# ArtistGrid registry — TrackerHub's live successor, served as CSV
# (https://artists.artistgrid.cx/artists.csv)
# ---------------------------------------------------------------------------

def _parse_csv_flag(value: str | None) -> bool | None:
    """"1" -> True, "0" -> False, anything else (incl. ArtistGrid's tri-state
    "2" for links_work, meaning "partially working") -> unknown."""
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def parse_artistgrid_csv(csv_text: str) -> list[TrackerEntry]:
    """Parse the ArtistGrid tracker registry into tracker entries.

    Columns: name, url, credit, links_work, updated, best. ``url`` is a bare
    Google Sheets file ID for almost every row, or a bare domain for the
    handful of non-Google trackers (e.g. "franktracker.net") — sheet IDs
    never contain a dot, which is what tells the two apart.
    """
    entries: list[TrackerEntry] = []
    for row in csv.DictReader(csv_text.splitlines()):
        name = (row.get("name") or "").strip()
        raw_url = (row.get("url") or "").strip()
        if not name or not raw_url:
            continue
        url = (
            f"https://{raw_url}/" if "." in raw_url
            else f"https://docs.google.com/spreadsheets/d/{raw_url}/edit"
        )
        entries.append(TrackerEntry(
            name=name,
            url=url,
            credit=(row.get("credit") or "").strip() or None,
            best=(row.get("best") or "").strip().lower() == "true",
            up_to_date=_parse_csv_flag(row.get("updated")),
            working_links=_parse_csv_flag(row.get("links_work")),
        ))
    entries.sort(key=lambda e: (not e.best, e.name.lower()))
    return entries
