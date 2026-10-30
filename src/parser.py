"""LeakSheet — HTML parser for Google Sheets tracker exports.

Parses the htmlview export of a Google Spreadsheet music tracker into
structured Artist/Era/Song/SongVersion objects.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from bisect import bisect_left
from collections import Counter
import unicodedata
from functools import lru_cache, partial
from typing import Callable, Iterable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote_plus, urljoin, urlparse


from src.config import COLUMN_ALIASES
from src.streaming import resolve_stream_url
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parser tuning constants
# ---------------------------------------------------------------------------

# Maximum number of rows to scan when looking for the header row.
# Some trackers have instruction/title rows before the actual column headers.
_MAX_HEADER_SCAN_ROWS = 11

# Cap on unmatched rows recorded for diagnostics — prevents unbounded list growth
# on trackers that have many footers, annotations, or oddly structured rows.
_MAX_UNMATCHED_ROWS = 50

# Rows scanned below a tagged heading for the era value that names it; bounds the scan
# on a long run of label rows.
_TAGGED_HEADING_LOOKAHEAD = 8


# ---------------------------------------------------------------------------
# Low-level HTML table extraction
# ---------------------------------------------------------------------------

# The HTML spec's own ceiling; an unbounded value would allocate that many cells.
_MAX_COLSPAN = 1000


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
                self._colspan = min(int(a.get("colspan", "1") or "1"), _MAX_COLSPAN)
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
except ImportError:  # pragma: no cover - lxml is a pinned dependency
    _lxml_html = None


def _cell_from_td(td) -> _Cell:
    """Build a _Cell from an lxml <td> element.

    Mirrors _TableExtractor semantics exactly: <br> becomes "\\n", img alt
    text joins the cell text, and each link records the line number the
    anchor closes on.
    """
    if not len(td):  # most cells: plain text, nothing to walk
        return _Cell(text=(td.text or "").strip())
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
                colspan = min(int(td.get("colspan", "1") or "1"), _MAX_COLSPAN)
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


_MAX_GRID_CELLS = 2_000_000
# htmlview renders these as U+FFFD; "\n" and "\t" pass through.
_GRID_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _grid_text(text: str) -> str:
    return _GRID_CONTROL_RE.sub("\ufffd", text.replace("\r\n", "\n").replace("\r", "\n"))


def _utf16_offsets(text: str) -> list[int]:
    """UTF-16 offset of every character, then the total: API run offsets count astral characters twice."""
    offsets = [0]
    for ch in text:
        offsets.append(offsets[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return offsets


def _line_breaks_before(text: str) -> list[int]:
    """Line breaks in text[:i] for every i, as _grid_text renders them: CRLF counts once."""
    counts = [0]
    for i, ch in enumerate(text):
        counts.append(counts[-1] + (ch == "\r" or (ch == "\n" and (i == 0 or text[i - 1] != "\r"))))
    return counts


def _grid_link(uri: str) -> str:
    # htmlview wraps every href once and _clean_link unwraps once, so a stored redirect survives.
    return "https://www.google.com/url?q=" + quote(uri, safe="")


def _grid_cell(value: dict) -> _Cell:
    raw = value.get("formattedValue") or ""
    if ((value.get("dataValidation") or {}).get("condition") or {}).get("type") == "BOOLEAN":
        raw = ""  # a checkbox renders no text in htmlview
    text = _grid_text(raw).strip()
    if hyperlink := value.get("hyperlink"):
        # htmlview renders a cell with a hyperlink as one anchor around all of it.
        return _Cell(text=text, links=[_grid_link(hyperlink)], link_lines=[_grid_text(raw).count("\n")])
    runs = value.get("textFormatRuns") or []
    chips = value.get("chipRuns") or []
    link_runs = [(i, uri) for i, run in enumerate(runs)
                 if (uri := ((run.get("format") or {}).get("link") or {}).get("uri"))]
    link_chips = [(chip.get("startIndex", 0), uri) for chip in chips
                  if (uri := ((chip.get("chip") or {}).get("richLinkProperties") or {}).get("uri"))]
    if not link_runs and not link_chips:
        return _Cell(text=text)
    # Linear in the cell, not per run: a cell can hold thousands of runs.
    offsets, breaks = _utf16_offsets(raw), _line_breaks_before(raw)

    def index(units: int) -> int:
        return min(bisect_left(offsets, units), len(raw))

    spans: list[tuple[int, int, str]] = []
    for i, uri in link_runs:
        end = index(runs[i + 1].get("startIndex", 0)) if i + 1 < len(runs) else len(raw)
        spans.append((index(runs[i].get("startIndex", 0)), end, uri))
    for units, uri in link_chips:
        start = index(units)
        spans.append((start, start + 1, uri))
    spans.sort()
    return _Cell(
        text=text,
        links=[_grid_link(uri) for _start, _end, uri in spans],
        link_lines=[breaks[min(end, len(raw))] for _start, end, _uri in spans],
    )


def _grid_hidden(meta: list, i: int) -> bool:
    m = meta[i] if i < len(meta) else {}
    return bool(m.get("hiddenByUser") or m.get("hiddenByFilter"))


def _grid_covered(merges: list, row_meta: list, n_rows: int, n_cols: int) -> set[tuple[int, int]]:
    """Cells a merge covers (all but its top row), which htmlview renders no <td> for."""
    covered: set[tuple[int, int]] = set()
    for m in merges:
        # htmlview drops a hidden row with its <td>s: a rowspan starting there covers nothing.
        if _grid_hidden(row_meta, m.get("startRowIndex", 0)):
            continue
        rows = range(m.get("startRowIndex", 0) + 1, min(m.get("endRowIndex", 0), n_rows))
        columns = range(m.get("startColumnIndex", 0), min(m.get("endColumnIndex", 0), n_cols))
        covered.update((r, c) for r in rows for c in columns)
    return covered


def _grid_row(r: int, cols: list[int], covered: set[tuple[int, int]], frozen_cols: int, cell_of) -> list[_Cell]:
    """One htmlview row: an empty freezebar <td> follows the frozen columns of every row."""
    row: list[_Cell] = []
    placed = not frozen_cols
    for c in cols:
        if not placed and c >= frozen_cols:
            row.append(_Cell())
            placed = True
        if (r, c) not in covered:
            row.append(cell_of(c))
    if not placed:
        row.append(_Cell())
    return row


def _grid_parts(sheet: dict) -> tuple[dict, list, list, list]:
    """(gridProperties, rowData, rowMetadata, columnMetadata) of one API sheet."""
    grid = (sheet.get("properties") or {}).get("gridProperties") or {}
    data = (sheet.get("data") or [{}])[0]
    return grid, data.get("rowData") or [], data.get("rowMetadata") or [], data.get("columnMetadata") or []


def _grid_cell_of(values: list):
    return lambda c: _grid_cell(values[c]) if c < len(values) else _Cell()


def extract_grid(sheet: dict) -> list[list[_Cell]]:
    """The rows `extract_table` gives for this sheet's htmlview, from Sheets API v4 JSON.

    In-cell images are not in the API, so no cell carries any. The htmlview quirks
    mirrored here: docs/decisions.md::parser.py::extract_grid.
    """
    grid, row_data, row_meta, col_meta = _grid_parts(sheet)
    n_rows = max(grid.get("rowCount", 0), len(row_data))
    n_cols = grid.get("columnCount", 0)
    # The body is trimmed but the grid size is not: an empty tab can declare millions of cells.
    if max(n_rows, 1) * n_cols > _MAX_GRID_CELLS:
        raise ValueError(f"grid of {n_rows} x {n_cols} cells is too large")
    place = partial(
        _grid_row,
        cols=[c for c in range(n_cols) if not _grid_hidden(col_meta, c)],
        covered=_grid_covered(sheet.get("merges") or [], row_meta, n_rows, n_cols),
        frozen_cols=grid.get("frozenColumnCount", 0),
    )
    frozen = grid.get("frozenRowCount", 0)
    rows: list[list[_Cell]] = []
    for r in range(n_rows):
        if frozen and r == frozen:
            rows.append(place(-1, cell_of=_grid_cell_of([])))
        if _grid_hidden(row_meta, r):
            continue
        row = place(r, cell_of=_grid_cell_of((row_data[r].get("values") or []) if r < len(row_data) else []))
        if row:
            rows.append(row)
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
        # Only fire on GLUED text ("noteswelcome to the tracker"). After a space the header
        # is a different column: "Project Type" is not Era, "Dates Added" is not "Date".
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
        # Colon-suffixed headers ('Track Titles:') must still match their alias.
        key = key.rstrip(":").strip()

        canonical = _match_column_alias(key)

        # No match on the full cell: try each line, for a column name on its own line
        # among notice text (e.g. "[notice]\nNotes").
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

    Otherwise `name` falls back to positional index 1 (see `_parse_song_row`),
    which may be a track-number column. Only unclaimed headers containing
    "title" or "name" as a whole word are considered.
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

    Returns ``(unknown, duplicate)``. *unknown* is a header no alias covers — the
    list worth reading when a new tracker looks wrong. *duplicate* is an aliased
    header whose field another column already claimed: a sheet-shape issue no
    alias work will fix.
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


# Keywords that mark an urgent notice. "X ... Y" pairs must share a line; each is
# checked from the FIRST X only, since a later X has less of the line after it.
_ALERT_KEYWORDS = re.compile(
    r"not working|shut down|shutdown|expired|broken|taken down|"
    r"dmca|copyright|removed|reuploaded?|reupload|unavailable|"
    r"\bno eta\b|in.progress.of",
    re.IGNORECASE,
)
_ALERT_PAIRS = [
    (re.compile(r"\bdown\b", re.IGNORECASE), re.compile(r"fix|working|progress|eta", re.IGNORECASE)),
    (re.compile(r"fix|working on", re.IGNORECASE), re.compile(r"asap|soon|eta", re.IGNORECASE)),
]


def _is_alert_line(line: str) -> bool:
    if _ALERT_KEYWORDS.search(line):
        return True
    for head, tail in _ALERT_PAIRS:
        m = head.search(line)
        if m and tail.search(line, m.end()):
            return True
    return False


def _line_links(cell: _Cell) -> dict[int, str]:
    """Line index → cleaned URL of the link on that line."""
    out: dict[int, str] = {}
    for link_idx, line_num in enumerate(cell.link_lines):
        if link_idx < len(cell.links):
            cleaned = _clean_link(cell.links[link_idx])
            if cleaned:
                out[line_num] = cleaned
    return out


def _is_column_label(line: str) -> bool:
    """A header-cell line that names a column (parenthetical ignored), not a notice."""
    norm = re.sub(r'\s+', ' ', line.lower())
    p = norm.find("(")
    return bool(_match_column_alias(norm[:p].strip() if p > 0 else norm))


class _NoticeCollector:
    """Deduplicated notices, at least 10 characters, outer parentheses dropped."""

    def __init__(self) -> None:
        self.notices: list[Notice] = []
        self._seen: set[str] = set()

    def add(self, text: str, link: str | None = None) -> None:
        text = text.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()
        if len(text) < 10 or text.lower() in self._seen:
            return
        self._seen.add(text.lower())
        kind = "alert" if any(_is_alert_line(line) for line in text.split("\n")) else "info"
        self.notices.append(Notice(text=text, link=link, kind=kind))


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
    collector = _NoticeCollector()
    for cell in header_row:
        links = _line_links(cell)
        for line_idx, line in enumerate(cell.text.strip().split("\n")):
            stripped = line.strip()
            if stripped and not _is_column_label(stripped):
                collector.add(stripped, links.get(line_idx))
    artist_lower = artist_name.lower() if artist_name else ""
    for cell in (c for row in pre_header_rows for c in row):
        _add_pre_header_notices(collector, cell, artist_lower)
    return collector.notices


def _add_pre_header_notices(collector: _NoticeCollector, cell: _Cell, artist_lower: str) -> None:
    text = cell.text.strip()
    # Skip empty cells and ones that are just the artist/tracker name
    if not text or text.lower() == artist_lower or ("tracker" in text.lower() and len(text) < 40):
        return
    links = _line_links(cell)
    for line_idx, line in enumerate(text.split("\n")):
        collector.add(line.strip(), links.get(line_idx))


# ---------------------------------------------------------------------------
# Row classification
# ---------------------------------------------------------------------------

# Era stats row forms: docs/decisions.md::parser.py::ERA_STATS_PATTERN. Leak-status
# words match on one pair; discography words need two (era_stats_match).
ERA_STATS_PATTERN = re.compile(
    r"(?<!\d)\d++\s++"
    r"("
    r"OG File|Total Full|Full|Tagged|Partial|Snippet|Stem|Unavailable"
    r"|Edited"                                                          # Michael Jackson
    r"|of Leaks|of Snippets|of Partials|of Recordings|of Unavailable|of Full"
    r"|Leaks?|Snippets?|Partials?"
    r"|Streaming|Off-Streaming|Off Streaming|On Streaming|On-Streaming"
    r"|tracks?|songs?"
    r"|Released|Deleted|Losts?|Privated"
    r"|Confirmed|Rumou?red"
    r")\b",
    re.IGNORECASE,
)

# Release-type counts: docs/decisions.md::parser.py::_DISCOGRAPHY_STATS_PATTERN
_DISCOGRAPHY_STATS_PATTERN = re.compile(
    r"(?<!\d)\d++\s++"
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

# Any "<int> <word>" pair, used only to count a cell's counts. The lookbehind starts
# each attempt at a digit run's first digit, keeping this linear.
_STAT_PAIR_RE = re.compile(r"(?<!\d)\d++\s++[A-Za-z]")
_MIN_DISCOGRAPHY_PAIRS = 2


def era_stats_match(text: str) -> bool:
    """True if *text* is an era stats block, in either tracker vocabulary."""
    if ERA_STATS_PATTERN.search(text):
        return True
    return (
        bool(_DISCOGRAPHY_STATS_PATTERN.search(text))
        and len(_STAT_PAIR_RE.findall(text)) >= _MIN_DISCOGRAPHY_PAIRS
    )

# Spreadsheet formula errors: never content.
# See docs/decisions.md::parser.py::broken-stats-formula
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

    Recognises the global stats footer's cells by SHAPE, since their wording
    ("99 Album Track", "43 Best Of") is in neither stats vocabulary. Requiring two
    lines keeps a one-line era name like "38 Special Sessions" out.
    """
    lines = [l for l in (EMOJI_RUN_RE.sub("", ln).strip() for ln in text.split("\n")) if l]
    if len(lines) < _MIN_STAT_ONLY_LINES:
        return False
    return all(_STAT_ONLY_LINE_RE.match(l) for l in lines)


# Standalone cell values that divide song groups (e.g. "surfaced" = officially
# released material), not song or era names.
SECTION_SEPARATORS = {
    "surfaced", "unsurfaced", "unavailable",
    "og files for released songs & alternate versions",
    "og files for released songs",
    "unknown collaborations",
    # Cross-tracker section labels
    "features", "collaborations", "collaboration", "featured",
    "collaborations & features", "loosies", "guest verses",
    "guest features",
    # Sub-section labels
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
    # Real era headers have a non-stats era name in some cell (or cell 0's first
    # line); global stats rows have only stat-like content.
    _NUMERIC_STAT_RE = re.compile(r"^\d+\s")
    for c in row:
        text = c.text.strip()
        if not text:
            continue
        # Check for images (era art) — a strong signal this is an era header
        if c.images:
            return True
        # A cell of nothing but counts holds no era name, whatever its vocabulary; without
        # this the global stats footer's cells read as digit-leading era names.
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
# Typographic quotes and dashes fold to ASCII so "Don’t" and "Don't" share a key.
_TYPOGRAPHIC_FOLD = str.maketrans(
    {"’": "'", "‘": "'", "‚": "'", "‛": "'", "“": '"', "”": '"',
     "–": "-", "—": "-", "‐": "-", "‑": "-", "−": "-"}
)

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

    # A broken formula is not a name; as an era, the abbreviated-era-name rule
    # below would absorb every later era into it.
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

    # Person name + social handle after paren stripping: "Fly (@damn4k)" (the
    # check above runs on the original text).
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
    # The text cell must be a short label: single-line, or a short first line whose
    # other lines are 'note: …' annotations (Carti: 'Full LQs\nnote: check the remasters tab…').
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
    # Prefer the longer/fuller name, unless both name different versions ([V1] vs [V10]).
    source_tag, target_tag = _era_tag_key(source.name), _era_tag_key(target.name)
    if source_tag and target_tag and source_tag != target_tag:
        return
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


# Emoji, counts and punctuation ahead of a footer keyword ("🔗 616 Total Links").
_FOOTER_LINE_LEAD_RE = re.compile(r"^[\W\d_]+")


def _is_tracker_footer(row: list[_Cell]) -> bool:
    """Check if a row belongs to the tracker footer (stats, changelogs, guidelines).

    A keyword must open a cell line: see docs/decisions.md::parser.py::_is_tracker_footer.
    """
    for cell in row:
        for line in cell.text.lower().split("\n"):
            if _FOOTER_KEYWORDS_RE.match(_FOOTER_LINE_LEAD_RE.sub("", line, count=1)):
                return True
    return False


def _normalize_unicode(text: str) -> str:
    """Normalize Unicode text by replacing diacritics with their base characters.

    Handles cases like "geëky" → "geeky", "ROSALÍA" → "ROSALIA".
    """
    if text.isascii():
        return text
    # NFKD decomposition splits characters like ë into e + combining diaeresis
    decomposed = unicodedata.normalize("NFKD", text)
    # Remove combining characters (diacritics)
    # Marks carry meaning outside Latin (か/が, и/й), so only Latin bases lose them.
    out: list[str] = []
    latin = False
    for c in decomposed:
        if unicodedata.combining(c):
            if not latin:
                out.append(c)
            continue
        latin = unicodedata.name(c, "").startswith("LATIN")
        out.append(c)
    return "".join(out)


def _era_match_key(full_era_name: str, *, keep_discriminators: bool = False) -> str:
    """Extract the matching key from an era name, lowercased for matching.

    *keep_discriminators* preserves a ``[V1]`` version tag and a parenthetical
    like ``(2018)``, which tell sibling eras apart on an Art tab; song rows omit
    both, so the default drops them. See docs/decisions.md::parser.py::art-version-keys.

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
    # Strip the trailing asterisk some trackers (Travis Scott) use for an era's
    # features sub-section, so "Rodeo*" resolves to "Rodeo".
    key = key.rstrip("*").strip()
    # Normalize Unicode diacritics (ë→e, á→a, etc.)
    key = _normalize_unicode(key).translate(_TYPOGRAPHIC_FOLD)
    key = key.lower()
    # Strip punctuation so "Meet The Woo, Vol. 2" matches "Meet The Woo Vol 2" and
    # "AT.LONG.LAST.A$AP" matches "AT LONG LAST A$AP".
    key = _PUNCT_STRIP_RE.sub(" ", key)
    key = _WHITESPACE_COLLAPSE_RE.sub(" ", key).strip()
    return key


def _era_tag_key(era_name: str) -> str:
    """The stripped key plus every version tag ("Moon Tape [V2]" → "moon tape [v2]"), or ""
    when the first line carries none. Tells apart siblings that share a stripped key."""
    first = era_name.split("\n")[0]
    tags = VERSION_TAG_PATTERN.findall(first)
    key = _era_match_key(first) if tags else ""
    return " ".join([key, *(f"[{t.lower()}]" for t in tags)]) if key else ""


def _song_match_key(name: str) -> str:
    """Stable normalized song identity key for cross-era version linkage.

    Same normalization recipe as era keys (diacritics, case, version tags,
    punctuation, whitespace) applied to a song base name, so "THIS ONE HERE"
    in WAR and "This One Here" in DONDA 2 share one key. Exposed to clients
    as ``Song.song_key``.
    """
    key = _normalize_unicode(name).translate(_TYPOGRAPHIC_FOLD)
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


# Both helpers run once per era key PER UNMATCHED ROW (millions of calls on a
# big tracker) over heavily repeating keys, hence the cache.
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

_REDIRECT_Q_RE = re.compile(r"(?:^|&)q=([^&]+)")
_HTTP_RE = re.compile(r"https?://[^\s/]", re.I | re.A)


def _clean_link(url: str) -> str:
    """Strip Google redirect wrapper from URLs; "" for anything but http(s).

    Google Sheets wraps links as: https://www.google.com/url?q=REAL_URL&...
    """
    url = url.strip()
    if "google.com/url" in url:
        # Same result as parse_qs(urlparse(url).query)["q"][0], at a fraction of the cost.
        query = url.partition("#")[0].partition("?")[2]
        m = _REDIRECT_Q_RE.search(query)
        if m:
            url = unquote_plus(m.group(1)).strip()
    # docs/decisions.md::parser.py::_clean_link
    return url if _HTTP_RE.match(url) else ""


# docs/decisions.md::parser.py::_split_links
_URL_START_RE = re.compile(r"https?://", re.I | re.A)
_ENCODED_WS = frozenset({"%20", "%09", "%0a", "%0d"})
# A scheme right after one of these is a wrapper's payload (web.archive.org/web/<ts>/https://…,
# href.li/?http://…), not a second link.
_PAYLOAD_PREV = frozenset("/=?#:&@%+")
# The same payload introducers, percent-encoded.
_ENCODED_PAYLOAD_PREV = frozenset({"%3d", "%2f", "%3f", "%26", "%3a", "%23"})
_GOOGLE_WRAPPER_RE = re.compile(r"https?://(?:www\.)?google\.com/url", re.I)


def _netloc(url: str) -> str:
    parts = url.split("/", 3)
    return parts[2].lower() if len(parts) > 2 else ""


def _split_urls(text: str, wrappers_only: bool = False) -> list[str]:
    """Split *text* at each URL that starts after whitespace or glued onto the previous one.

    *wrappers_only* splits an unwrapped href only at raw whitespace or a new Google wrapper:
    a wrapper's own ``q=`` holds its URLs unencoded, and its tracking tail must stay with it.
    """
    text = text.strip()
    pieces: list[str] = []
    glued: list[bool] = []  # glued[k]: pieces[k] runs straight into pieces[k + 1]
    start = 0
    for m in _URL_START_RE.finditer(text, 1):
        i = m.start()
        j = i
        while True:  # step back over whitespace, raw or percent-encoded
            if j and text[j - 1].isspace():
                j -= 1
            elif j >= 3 and text[j - 3 : j].lower() in _ENCODED_WS:
                j -= 3
            else:
                break
        if wrappers_only and not (
            _GOOGLE_WRAPPER_RE.match(text, i) or any(c.isspace() for c in text[j:i])
        ):
            continue
        if j == i:
            prev = text[i - 1]
            if text[i - 3 : i].lower() in _ENCODED_PAYLOAD_PREV:
                continue
            # A same-host scheme after "/" is a paste restarted, not a wrapper.
            if prev in _PAYLOAD_PREV and not (
                prev == "/" and _netloc(text[start:i]) == _netloc(text[i : i + 300])
            ):
                continue
        if j > start:
            pieces.append(text[start:j].rstrip(" ,;|"))
            glued.append(j == i)
        start = i
    pieces.append(text[start:])
    # A glued piece that is a prefix of the next one is an abandoned paste.
    kept = [
        p for k, p in enumerate(pieces)
        if not (k < len(glued) and glued[k] and pieces[k + 1].startswith(p))
    ]
    return list(dict.fromkeys(p for p in kept if p))


def _split_links(url: str) -> list[str]:
    """One cleaned link per URL in *url*: a cell href or text can hold several.

    Splits before unwrapping so each Google ``url?q=`` wrapper unwraps on its own, and after,
    since a wrapper's payload can hold more URLs.
    """
    links = [link for part in _split_urls(url, wrappers_only=True) for link in _split_urls(_clean_link(part))]
    return list(dict.fromkeys(links))


def _extract_links_from_cell(cell: _Cell) -> list[str]:
    """Get cleaned links from a cell, one per URL."""
    return [link for raw in cell.links for link in _split_links(raw)]


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
    sibling era registered the shared key first in the global dicts. The tag
    keys also find a tagged row's sibling era.
    """
    keys: set[str] = set()
    primary = _era_match_key(era.name)
    if primary:
        keys.add(primary)
    full = _normalize_unicode(era.name).lower().strip()
    if full:
        keys.add(full)
    tag_key = _era_tag_key(era.name)
    if tag_key:
        keys.add(tag_key)
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
            for part_key in (_era_match_key(part), _era_tag_key(part)):
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
    (Travis-style headers embed the art in the name cell).
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

    # Image-based era name: the name cell has an image but no usable text (empty, or
    # purely parenthetical). The real name is backfilled from the first song row.
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


# Column labels that mark an artwork tab, which otherwise parses as one "song" per
# cover. Two hits required: a lone "Image" column also appears on physical-release tabs.
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

# The glossary tab every template ships resolves to exactly these two columns. A
# statement about the WHOLE resolved header: a headerless song tab resolves to {}.
_GLOSSARY_COLUMNS = frozenset({"available_length", "quality"})


def is_song_tab(header_row: list[_Cell], col_map: dict[str, int]) -> bool:
    """Return False for tabs that hold something other than songs.

    Glossaries, artwork indexes, interview logs, setlists and BPM/key tabs parse
    into plausible-looking junk. Rejection is only ever on a POSITIVE signature,
    never on a missing column: see docs/decisions.md::parser.py::is_song_tab.
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

    A no-op for Google's htmlview export (always absolute); self-hosted trackers
    emit "/assets/<sha>.jpg".
    """
    for era in eras:
        if era.art_url and not urlparse(era.art_url).netloc:
            era.art_url = urljoin(source_url, era.art_url)


class _TagIndex:
    """Newest era per own tag key, so a tagged row finds its sibling without scanning eras."""

    def __init__(self) -> None:
        self.latest: dict[str, Era] = {}
        self.upto = 0
        self.unnamed: list[Era] = []  # indexed once a backfilled name gives it keys

    def find(self, tag_key: str, eras: list[Era], own_keys: Callable[[Era], set[str]]) -> Era | None:
        pending, self.unnamed = self.unnamed + eras[self.upto:], []
        self.upto = len(eras)
        # Pending is in era order, so a newer era overwrites an older one.
        for era in pending:
            keys = own_keys(era)
            if not keys:
                self.unnamed.append(era)
            for key in keys:
                self.latest[key] = era
        return self.latest.get(tag_key)


def _resolve_row_era(
    row_era: str,
    current_era: Era | None,
    eras: list[Era],
    era_by_key: dict[str, Era],
    era_by_key_fallback: dict[str, Era],
    own_keys_cache: dict[int, set[str]],
    tag_index: _TagIndex,
) -> tuple[Era | None, bool, bool]:
    """The era a row's era-column value names, whether only a fuzzy match found it, and
    whether it is a tagged sibling of the current era (which then stays current).

    Tried in order: the current era's own keys, the nearest era whose own name carries the
    row's version tags, the current era's stripped key, the primary then the fallback keys
    (each by full then stripped key), a fuzzy match on the current era, then on all.
    A positional fuzzy hit is registered as a fallback key for the rows that follow.
    """
    def own_keys(era: Era) -> set[str]:
        own = own_keys_cache.get(id(era))
        if own is None:
            own = own_keys_cache[id(era)] = _era_own_keys(era)
        return own

    norm = _normalize_unicode(row_era).lower()
    stripped = _era_match_key(row_era)
    tag_key = _era_tag_key(row_era)
    own = own_keys(current_era) if current_era is not None else set()
    if norm in own or tag_key in own:
        return current_era, False, False
    # Own names only: a section-label alias never makes an era a tagged sibling.
    tagged = tag_index.find(tag_key, eras, own_keys) if tag_key else None
    if tagged is not None:
        return tagged, False, stripped in own
    if stripped in own:
        return current_era, False, False
    for keys in (era_by_key, era_by_key_fallback):
        for key in (norm, stripped):
            era = keys.get(key)
            if era is not None:
                return era, False, False
    cur_key = _era_match_key(current_era.name) if current_era is not None and current_era.name else ""
    if cur_key and _fuzzy_era_match(norm, {cur_key: current_era}):
        era_by_key_fallback.setdefault(stripped, current_era)
        logger.debug("Positional fuzzy match: %r → current era %r", norm, current_era.name)
        return current_era, True, False
    era = _fuzzy_era_match(norm, era_by_key)
    if era is not None:
        logger.debug("Fuzzy era match: %r → %r", norm, era.name)
    return era, era is not None, False


def _heads_tagged_era(
    label: str,
    rows: list[list[_Cell]],
    row_idx: int,
    col_map: dict[str, int],
    current_era: Era,
    declared_keys: set[str],
) -> bool:
    """Whether a single-line Name-column row such as "Album [V6]" starts an era, not a section.

    The first Era-column value below it must carry the same version tags, and the label
    must not repeat a declared era's tag or be a version group of the era above (the
    untagged album it tags). See docs/decisions.md::parser.py::tagged-name-row-era.
    """
    tag_key = _era_tag_key(label)
    if not tag_key:
        return False
    own = _era_own_keys(current_era)
    if tag_key in own or tag_key in declared_keys:
        return False
    if not _era_tag_key(current_era.name) and _era_match_key(label) in own:
        return False
    era_col = col_map.get("era", 0)
    for row in rows[row_idx + 1 : row_idx + 1 + _TAGGED_HEADING_LOOKAHEAD]:
        if _is_empty_row(row) or _is_section_separator(row):
            continue
        if _is_era_header(row):
            return False
        row_era = _get_cell_text(row, era_col)
        if row_era:
            return _era_tag_key(row_era) == tag_key
        if sum(1 for c in row if c.text.strip()) > 3:
            return False
    return False


def _stats_less_era(row: list[_Cell], name: str, col_map: dict[str, int]) -> Era:
    """An era from a header row with no stats cell: timeline from Notes, else Name."""
    timeline_raw = _get_cell_text(row, col_map.get("notes", 2)) or _get_cell_text(
        row, col_map.get("name", 1)
    )
    return Era(
        name=name,
        timeline=parse_timeline(timeline_raw) if timeline_raw else [],
        art_url=_first_row_image(row),
        sections=[Section()],
    )


def _sample_unmatched(sample: list[str], row_idx: int, row: list[_Cell]) -> None:
    """Keep a capped diagnostic sample of rows no rule claimed."""
    if len(sample) < _MAX_UNMATCHED_ROWS:
        row_text = " | ".join(c.text.strip() for c in row if c.text.strip())[:200]
        if row_text:
            sample.append(f"Row {row_idx}: {row_text}")


class _SheetWalk:
    """The row walk of `parse_sheet`: era/section/footer/song classification over one tab.

    One method per row kind, tried in a fixed order; each returns True when it consumed the row.
    """

    def __init__(self, rows: list[list[_Cell]], header_row_idx: int, col_map: dict[str, int], notices: list[Notice]):
        self.rows = rows
        self.header_row_idx = header_row_idx
        self.col_map = col_map
        self.notices = notices
        # Tabs without era header rows: the Era column is the only era signal, so it is
        # authoritative (the abbreviated-era heuristic would collapse the tab into one era).
        self.flat_era_mode = not any(_is_era_header(r) for r in rows[header_row_idx + 1:])
        # How often each era-column value occurs: a one-character value seen once
        # is a typo; seen repeatedly it is an era the sheet declares only in cells.
        era_idx = col_map.get("era", 0)
        self.era_value_counts = Counter(
            _get_cell_text(r, era_idx).split("\n")[0].strip() for r in rows[header_row_idx + 1:]
        )
        self.eras: list[Era] = []
        self.current_era: Era | None = None
        # Lowercased, parenthetical- and version-tag-stripped era key → Era.
        self.era_by_key: dict[str, Era] = {}
        # Fallback registrations, consulted only when the primary dict misses, so a
        # genuine "Ay Ay" era declared later beats a "38 Baby / Ay Ay" slash part.
        self.era_by_key_fallback: dict[str, Era] = {}
        # Eras whose name cell had an image but no usable text — backfill from
        # the first song row's era column. Holds id(era) values.
        self.needs_name_backfill: set[int] = set()
        # id(era) → its own key forms, for the positional-exact prior.
        self.era_own_keys_cache: dict[int, set[str]] = {}
        self.tag_index = _TagIndex()
        # Own keys of eras[:declared_upto], so a repeated tagged heading is found in O(1).
        self.declared_keys: set[str] = set()
        self.declared_upto = 0
        # (id(era), song base name) → Song, for O(1) version grouping
        self.song_index: dict[tuple[int, str], Song] = {}
        self.in_footer = False
        self.song_rows = 0
        self.skipped_rows = 0
        self.unmatched_rows: list[str] = []
        self.unmatched_total = 0
        self.footer_rows = 0
        self.fuzzy_matched_rows = 0

    # -- shared steps ---------------------------------------------------------

    def _add(self, era: Era, version: SongVersion) -> None:
        _add_version_to_era(era, version, self.song_index)
        self.song_rows += 1

    def _open_era(self, era: Era, key_text: str, primary: dict[str, Era] | None = None) -> None:
        self.eras.append(era)
        _register_era_keys(era, key_text, self.era_by_key if primary is None else primary, self.era_by_key_fallback)
        self.current_era = era

    def _unmatched(self, row_idx: int, row: list[_Cell]) -> None:
        self.skipped_rows += 1
        self.unmatched_total += 1
        _sample_unmatched(self.unmatched_rows, row_idx, row)

    # -- the walk -------------------------------------------------------------

    def walk(self) -> None:
        for row_idx, row in enumerate(self.rows):
            # Skip the header row and any title/instruction rows before it, and empty rows.
            if row_idx <= self.header_row_idx or _is_empty_row(row):
                continue
            self._row(row_idx, row)

    def _row(self, row_idx: int, row: list[_Cell]) -> None:
        if self.current_era is None and self._meta_banner(row):
            return
        # Era header FIRST (before separator/footer checks); it also resets footer state.
        # See docs/decisions.md::parser.py::parse_sheet — era header checked before section separator
        if self._era_header(row) or self._section_separator(row) or self._footer(row):
            return
        era_col = self.col_map.get("era", 0)
        row_era = _get_cell_text(row, era_col)
        if row_era:
            if not self._backfill_era_name(row, row_era):
                self._era_column_row(row_idx, row, row_era, era_col)
            return
        name_val = _get_cell_text(row, self.col_map.get("name", 1))
        if name_val and self._name_column_row(row_idx, row, name_val):
            return
        if not name_val and self._section_or_spill(row):
            return
        if self._positional_song(row):
            return
        self._unmatched(row_idx, row)

    def _meta_banner(self, row: list[_Cell]) -> bool:
        """A meta banner between the header and the first era (Travis Scott:
        '| Last Updated: … | Hover over the headers … |') becomes a notice."""
        filled = [c for c in row if c.text.strip()]
        if not (
            len(filled) == 1
            and not filled[0].links
            and re.search(r"last updated|hover over|how to use", filled[0].text, re.IGNORECASE)
        ):
            return False
        text = filled[0].text.strip().strip("|").strip()
        # Dedupe against header notices and repeated banner rows (this append site
        # bypasses _extract_header_notices' own seen-set).
        if text.lower() not in {n.text.lower() for n in self.notices}:
            self.notices.append(Notice(text=text, link=None, kind="info"))
        return True

    def _era_header(self, row: list[_Cell]) -> bool:
        if not _is_era_header(row):
            return False
        self.in_footer = False
        era, needs_backfill = _parse_era_header_row(row, self.col_map)
        self._open_era(era, era.name)
        if needs_backfill:
            self.needs_name_backfill.add(id(era))
        return True

    def _section_separator(self, row: list[_Cell]) -> bool:
        """Section separators become named sections within the current era."""
        if not _is_section_separator(row):
            return False
        if self.current_era is not None:
            non_empty = [c for c in row if c.text.strip()]
            label = non_empty[0].text.strip() if non_empty else ""
            if label:
                self.current_era.sections.append(Section(name=label))
        return True

    def _footer(self, row: list[_Cell]) -> bool:
        """Footer rows are flagged, not a stop: a later era header resets `in_footer`."""
        name_col_text = _get_cell_text(row, self.col_map.get("name", 1)).strip().lower()
        if name_col_text in _NAME_FOOTER_KEYWORDS or _is_tracker_footer(row):
            self.in_footer = True
        if self.in_footer:
            self.footer_rows += 1
        return self.in_footer

    def _backfill_era_name(self, row: list[_Cell], row_era: str) -> bool:
        """See docs/decisions.md::parser.py::backfill-era-priority."""
        era = self.current_era
        if era is None or id(era) not in self.needs_name_backfill:
            return False
        era.name = row_era
        _register_era_keys(era, row_era, self.era_by_key, self.era_by_key_fallback)
        self.needs_name_backfill.discard(id(era))
        version = _parse_song_row(row, self.col_map)
        if version:
            self._add(era, version)
        return True

    # -- rows with an Era-column value -----------------------------------------

    def _era_column_row(self, row_idx: int, row: list[_Cell], row_era: str, era_col: int) -> None:
        # Positional-prior order: docs/decisions.md::parser.py::parse_sheet — positional-prior era matching
        matched_era, fuzzy, sibling = _resolve_row_era(
            row_era, self.current_era, self.eras, self.era_by_key, self.era_by_key_fallback,
            self.era_own_keys_cache, self.tag_index,
        )
        self.fuzzy_matched_rows += fuzzy
        if matched_era is not None:
            # A tagged row's hop to a sibling keeps the header it sits under current.
            if not sibling:
                self.current_era = matched_era
            version = _parse_song_row(row, self.col_map)
            if version and _is_section_label_version(version, row, era_col):
                matched_era.sections.append(Section(name=version.name, notes=version.notes))
            elif version:
                self._add(matched_era, version)
        elif self.current_era is not None:
            self._unknown_era_under_current(row, row_era, self.current_era)
        else:
            self._unknown_era_first(row_idx, row, row_era)

    def _unknown_era_under_current(self, row: list[_Cell], row_era: str, current: Era) -> None:
        """No key matched, but an era is open: same name (case-insensitive) joins it,
        a different one may start a new era."""
        current_key = _era_match_key(current.name) if current.name else ""
        version = _parse_song_row(row, self.col_map)
        if current_key and _era_match_key(row_era) == current_key:
            # Same era (abbreviated or exact) — assign to current
            if version:
                self._add(current, version)
            elif sum(1 for c in row if c.text.strip()) <= 3:
                current.sections.append(Section(name=row_era))
        elif version and _looks_like_era_name(row_era):
            self._plausible_new_era(row_era, version, current)
        elif version:
            # Not a plausible era name but has song data: the current era is the fallback.
            self._add(current, version)
        elif sum(1 for c in row if c.text.strip()) <= 2 or not _looks_like_era_name(row_era):
            # No song data and very few filled cells: a sub-era section of the current era.
            current.sections.append(Section(name=row_era))
        else:
            # Enough data to be an era header without stats
            self._open_era(_stats_less_era(row, row_era, self.col_map), row_era)

    def _plausible_new_era(self, row_era: str, version: SongVersion, current: Era) -> None:
        """A different, era-like name on a song row: auto-create a new era, but prefer
        positional assignment when the row has real song data."""
        stripped = row_era.strip()
        # Abbreviated era names: docs/decisions.md::parser.py::abbreviated-era-names.
        # Off in flat_era_mode, where a new Era-column value is a new era.
        if _has_song_data(version) and not self.flat_era_mode:
            self._add(current, version)
            self.era_by_key_fallback.setdefault(_era_match_key(row_era), current)
        elif len(stripped) <= 1 and self.era_value_counts[stripped] <= 1 and not self.flat_era_mode:
            # A one-character era cell on a row with no song data is a typo on a sub-era
            # label (Ye: "x"), not a new era holding one fake song.
            current.sections.append(Section(name=version.name, notes=version.notes))
        else:
            # Auto-created eras keep the row's own song (docs/decisions.md::parser.py::parse_sheet
            # — auto-created eras keep their row's song).
            self._open_era(Era(name=row_era, sections=[Section()]), row_era)
            self._add(self.current_era, version)

    def _unknown_era_first(self, row_idx: int, row: list[_Cell], row_era: str) -> None:
        """No era open yet: auto-create one from this row (trackers with no era headers,
        Young Thug etc.)."""
        if not _looks_like_era_name(row_era):
            # Announcements, footers and other non-era rows
            self._unmatched(row_idx, row)
            return
        version = _parse_song_row(row, self.col_map)
        if version:
            self._open_era(Era(name=row_era, sections=[Section()]), row_era)
            self._add(self.current_era, version)
        else:
            # No song data — stats-less era header (Kid Cudi style)
            self._open_era(_stats_less_era(row, row_era, self.col_map), row_era)

    # -- rows without an Era-column value ---------------------------------------

    def _name_column_row(self, row_idx: int, row: list[_Cell], name_val: str) -> bool:
        """Sub-era header vs. section label — see docs/decisions.md::parser.py::sub-era-header.

        Only short rows (three cells or fewer) are claimed; longer ones fall through to the
        positional fallback."""
        if sum(1 for c in row if c.text.strip()) > 3:
            return False
        # Split multi-line name cells (e.g. "The Graduates\n(2007 - 2009)")
        # and use only the first line as the era display name.
        name_first_line = name_val.split("\n")[0].strip()
        # A \n means a <br>-separated second line (year range) — reliable
        # signal that this row is a stats-less era header, not a section.
        has_multiline_name = "\n" in name_val
        heads_tagged = (
            self.current_era is not None and not has_multiline_name
            and self._heads_tagged(name_first_line, row_idx)
        )
        if heads_tagged or (has_multiline_name and _looks_like_era_name(name_first_line)):
            self._stats_less_header(row, name_val, name_first_line, heads_tagged)
        elif self.current_era is not None:
            # Single-line section label ("Other Media", "OG / Uncut Files"): a named section
            # of the current era; later song rows auto-create eras if needed.
            notes = _get_cell_text(row, self.col_map["notes"]).strip() if "notes" in self.col_map else ""
            self.current_era.sections.append(Section(name=name_first_line, notes=notes or None))
            # Section-label-as-alias — see docs/decisions.md::parser.py::section-label-alias
            _register_era_keys(self.current_era, name_first_line, self.era_by_key_fallback)
        else:
            # No current era — create one from the name column (Yung Lean style trackers).
            self._open_era(Era(name=name_first_line, sections=[Section()]), name_val)
        return True

    def _heads_tagged(self, name_first_line: str, row_idx: int) -> bool:
        for era in self.eras[self.declared_upto:]:
            self.declared_keys |= _era_own_keys(era)
        self.declared_upto = len(self.eras)
        return _heads_tagged_era(
            name_first_line, self.rows, row_idx, self.col_map, self.current_era, self.declared_keys
        )

    def _stats_less_header(self, row: list[_Cell], name_val: str, name_first_line: str, heads_tagged: bool) -> None:
        """Stats-less era header: multi-line name (Travis style) or a tagged heading its
        rows name. Captures the description and the era art."""
        name_col_idx = self.col_map.get("name", 1)
        desc_text = _get_cell_text(row, self.col_map.get("notes", 2))
        new_era = Era(
            name=name_first_line,
            art_url=_first_row_image(row, prefer_idx=name_col_idx),
            description=desc_text or None,
            sections=[Section()],
        )
        # Register full name_val so _era_match_key strips the parenthetical year and
        # matches e.g. "The Graduates". A tagged heading only aliases, so a later
        # untagged "Album" era keeps its own key.
        self._open_era(new_era, name_val, self.era_by_key_fallback if heads_tagged else None)

    def _section_or_spill(self, row: list[_Cell]) -> bool:
        """Short single-line text in a non-era cell may be a section label (Carti's
        "WLR Higher Bitrate Files" in Notes, with Era and Name empty)."""
        era = self.current_era
        if era is None:
            return False
        # Timeline continuation row: the era header's timeline spills into a row holding
        # only '(date) - event' text (Carti official).
        filled = [c.text.strip() for c in row if c.text.strip()]
        if len(filled) == 1 and filled[0].startswith("("):
            spill_events = parse_timeline(filled[0])
            if spill_events:
                era.timeline = list(era.timeline or []) + spill_events
                return True
        dyn_label = _is_dynamic_section_label(row, self.col_map)
        if dyn_label:
            era.sections.append(Section(name=dyn_label))
            return True
        return False

    def _positional_song(self, row: list[_Cell]) -> bool:
        """See docs/decisions.md::parser.py::positional-fallback."""
        if self.current_era is None:
            return False
        version = _parse_song_row(row, self.col_map)
        if version and (version.name or _has_song_data(version)):
            self._add(self.current_era, version)
            return True
        return False

    def metadata(self) -> ParseMetadata:
        total_rows = len(self.rows) - 1 - self.header_row_idx  # exclude header and pre-header rows
        unknown_columns, duplicate_columns = detect_dropped_columns(self.rows[self.header_row_idx], self.col_map)
        return ParseMetadata(
            total_rows=total_rows,
            song_rows=self.song_rows,
            skipped_rows=self.skipped_rows,
            unmatched_rows=self.unmatched_rows,
            unmatched_rows_total=self.unmatched_total,
            footer_rows=self.footer_rows,
            other_rows=max(0, total_rows - self.song_rows - self.skipped_rows - self.footer_rows),
            fuzzy_matched_rows=self.fuzzy_matched_rows,
            dropped_columns=unknown_columns,
            duplicate_columns=duplicate_columns,
        )


def parse_sheet(
    html_content: str, artist_name: str, source_url: str | None = None
) -> Artist:
    """Parse a Google Sheets HTML export into an Artist model.

    This is the main entry point for parsing a single tracker.

    *source_url* is the URL the HTML came from, used to resolve relative image
    sources. Optional: without it relative URLs pass through unchanged.
    """
    rows = extract_table(html_content)
    if not rows:
        # An empty ParseMetadata, not None: zeroes state that nothing was read and keep
        # the row-accounting identity true on every path.
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

    # Step 1b: extract announcement notices from header cells and pre-header rows.
    pre_header_rows = rows[:header_row_idx] if header_row_idx > 0 else []
    notices = _extract_header_notices(rows[header_row_idx], pre_header_rows, artist_name)

    # Step 2: walk rows, classify and extract
    walk = _SheetWalk(rows, header_row_idx, col_map, notices)
    walk.walk()

    # Step 3: detect and parse global stats row
    tracker_stats = _find_global_stats(rows)

    # Merge 0-song stub eras — see docs/decisions.md::parser.py::merge-stub-eras
    eras = _merge_empty_stub_eras(walk.eras)

    if source_url:
        _absolutize_era_art(eras, source_url)

    # Step 3c: consolidate group labels within each era's sections
    for era in eras:
        _consolidate_group_labels(era)
        _sort_era_versions(era)
    _reconcile_title_misreads(eras)

    # Step 4: build parse metadata
    metadata = walk.metadata()
    logger.debug(
        "Parsed %r: %d eras, %d song rows, %d skipped, %d fuzzy-matched era rows",
        artist_name, len(eras), walk.song_rows, walk.skipped_rows, walk.fuzzy_matched_rows,
    )
    if walk.unmatched_rows:
        # DEBUG: runs per candidate tab, and parse_metadata already carries these rows.
        logger.debug(
            "Parser found %d unmatched rows in %r (showing first %d): %s",
            len(walk.unmatched_rows), artist_name, min(5, len(walk.unmatched_rows)),
            " | ".join(walk.unmatched_rows[:5]),
        )

    return Artist(
        name=artist_name,
        slug=slugify(artist_name),
        eras=_disambiguate_era_names(eras),
        tracker_stats=tracker_stats,
        parse_metadata=metadata,
        notices=notices,
    )


def _reconcile_title_misreads(eras: list[Era]) -> None:
    """Undo two name-cell misreads by checking them against the tracker's own names.

    See docs/decisions.md::parser.py::_reconcile_title_misreads. A single cell
    cannot tell these apart; the rest of the tracker can.

    - An alias line "(With Child, Stay On Em)" matches the "(with X)" credit
      form, so the version got a collaboration "Child, Stay On Em" and lost both
      alt titles. Undone only when every name matches a title or alt title
      elsewhere in the same song family — real collabs ("(With Eminem)") never
      do.
    - An alias line "(Bitch, Don't Kill My Vibe)" is split on its comma into
      "Bitch" and "Don't Kill My Vibe". Rejoined when the joined text is a song
      title somewhere in the tracker.
    """
    songs = [song for era in eras for section in era.sections for song in section.songs]
    titles: set[str] = set()
    family_names: dict[str, set[str]] = {}
    for song in songs:
        title_key = _song_match_key(song.base_name)
        titles.add(title_key)
        names = family_names.setdefault(song.song_key or title_key, set())
        names.add(title_key)
        for version in song.versions:
            names.update(_song_match_key(alt) for alt in version.alt_titles)
    titles.discard("")

    for song in songs:
        names = family_names.get(song.song_key or _song_match_key(song.base_name), set())
        names.discard("")
        for version in song.versions:
            if len(version.alt_titles) > 1:
                version.alt_titles = _rejoin_split_aliases(version.alt_titles, titles)
            collab = version.collaboration
            if not collab:
                continue
            parts = [p.strip() for p in collab.split(", ") if p.strip()]
            if (
                parts
                and _song_match_key(f"With {parts[0]}") in names
                and all(
                    _song_match_key(p) in names or _song_match_key(f"With {p}") in names
                    for p in parts[1:]
                )
            ):
                restored = [f"With {parts[0]}", *parts[1:]]
                version.alt_titles = version.alt_titles + [
                    alt for alt in restored if alt not in version.alt_titles
                ]
                version.collaboration = None


def _rejoin_split_aliases(alts: list[str], titles: set[str]) -> list[str]:
    """Rejoin consecutive aliases whose comma-joined text is a known song title."""
    out: list[str] = []
    i = 0
    while i < len(alts):
        for j in range(len(alts), i + 1, -1):
            joined = ", ".join(alts[i:j])
            if _song_match_key(joined) in titles:
                out.append(joined)
                i = j
                break
        else:
            out.append(alts[i])
            i += 1
    return out


def _disambiguate_era_names(eras: list[Era]) -> list[Era]:
    """Guarantee every era in a tracker has a distinct, non-empty name.

    Era name is every client's identity key (iOS `Era.id`, `EraRow.id`, expand
    state), and SwiftUI silently keeps only the first row per duplicate id.
    Renaming here fixes every client at once.
    """
    taken: set[str] = set()
    out: list[Era] = []
    for i, era in enumerate(eras, start=1):
        base = (era.name or "").strip() or f"Untitled Era {i}"
        name, n = base, 1
        while name in taken:  # also skips a real "Foo (2)" seen earlier
            n += 1
            name = f"{base} ({n})"
        taken.add(name)
        out.append(era.model_copy(update={"name": name}) if name != era.name else era)
    return out


# Which stat group a cell holds, by the labels it carries. Independent: one cell may
# hold several stat lines.
_GLOBAL_STAT_GROUPS = (
    ("links", ("Total Link", "Missing Links")),
    ("quality", ("Lossless", "CD Quality")),
    ("availability", ("Total Full", "OG Files", "OG File")),
    ("highlights", ("Best Of", "Special", "Grails")),
)


def _global_stats_of_row(row: list[_Cell]) -> TrackerStats | None:
    """The tracker stats a footer row holds, or None when it is not the stats row."""
    texts = dict.fromkeys(("links", "quality", "availability", "highlights"), "")
    for cell in row:
        for group, labels in _GLOBAL_STAT_GROUPS:
            if any(label in cell.text for label in labels):
                texts[group] = cell.text
    stats = parse_tracker_stats(texts["links"], texts["quality"], texts["availability"], texts["highlights"])
    # A footer may hold all its stats in one cell, so count parsed fields. An
    # era header or a note that mentions a total yields at most one field.
    parsed = sum(1 for v in stats.model_dump().values() if v)
    if parsed < 2 or (parsed < 4 and _is_era_header(row)):
        return None
    return stats


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
        if any("Total Link" in c.text or "Total Full" in c.text for c in row):
            stats = _global_stats_of_row(row)
            if stats is not None:
                return stats
    return None


# Compound availability (Travis Scott, no Quality column): '<avail> - HQ',
# 'Unconfirmed (Snippet - LQ)'. No leading \s* (quadratic): the caller strips.
_COMPOUND_QUALITY_PATTERN = re.compile(r"-\s*(~?)(HQ|LQ|CDQ)\b")
# Stars may be separated by whitespace or newlines ("⭐\n⭐\n⭐"); the rating counts
# star glyphs. Scanned from the end: an end-anchored regex is quadratic.
_STAR_CHARS = "⭐★"
_STAR_RUN_CHARS = "⭐★☆"
_COMPOUND_QUALITY_NAMES = {
    "HQ": "High Quality", "LQ": "Low Quality", "CDQ": "CD Quality",
}

# U+FE0F (invisible emoji presentation selector) often follows "⭐" and would
# break a star run, so selectors are removed first.
_VARIATION_SELECTORS = str.maketrans("", "", "️︎")


def _trailing_star_rating(text: str) -> tuple[str, int | None]:
    """Split a trailing star run off *text*: ("Full - HQ", 4) for "Full - HQ ⭐⭐⭐⭐☆".

    The run is the trailing stretch of stars and whitespace; it counts only if
    it holds a filled star, and the rating is the number of filled stars.
    """
    run_start = len(text)
    while run_start and (text[run_start - 1].isspace() or text[run_start - 1] in _STAR_RUN_CHARS):
        run_start -= 1
    first = next((i for i in range(run_start, len(text)) if text[i] in _STAR_CHARS), None)
    if first is None:
        return text, None
    stars = sum(1 for c in text[first:] if c in _STAR_CHARS)
    return text[:first].rstrip(), min(stars, 5)


def _split_compound_availability(text: str) -> tuple[str, str | None, int | None]:
    """Split a compound availability value into (availability, quality, rating).

    Only used when the tracker has no dedicated Quality column. Returns the
    input unchanged (with None quality/rating) when no marker is present.
    """
    text = text.translate(_VARIATION_SELECTORS)
    text, rating = _trailing_star_rating(text)

    quality = None
    qm = _COMPOUND_QUALITY_PATTERN.search(text)
    if qm:
        quality = _COMPOUND_QUALITY_NAMES[qm.group(2)]
        start = qm.start()
        while start and text[start - 1].isspace():
            start -= 1
        text = (text[:start] + text[qm.end():])
        # Collapse artifacts left by the removal: '()' and stray whitespace
        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"[ \t]+", " ", text.replace("\n", " ")).strip()

    return text, quality, rating


def _opt_col(row: list[_Cell], col_map: dict[str, int], key: str) -> str | None:
    """A dedicated column's text, or None when the column is absent or empty."""
    return _get_cell_text(row, col_map.get(key, -1)) or None


def _song_title(after_badge: str, title: str, alt_titles: list[str]) -> tuple[str, str | None, list[str]] | None:
    """(title, version tag, alt titles) of a name cell, or None when nothing names the song."""
    # "(unfinished)"/"[unfinished]" is a status tag, not an alt name: move it from
    # alt_titles to version_tag (only if no tag was found).
    found_unfinished = any(_UNFINISHED_RE.fullmatch(t.strip()) for t in alt_titles)
    if found_unfinished:
        alt_titles = [t for t in alt_titles if not _UNFINISHED_RE.fullmatch(t.strip())]
    # Base name (tag stripped), so the UI doesn't show the tag twice.
    version_tag, title = extract_version_tag(title)
    # A credit-only name cell leaves no title: borrow an alt title or the raw line.
    if not title:
        raw_line = next((ln.strip() for ln in after_badge.split("\n") if ln.strip()), "")
        title = alt_titles.pop(0) if alt_titles else raw_line
        if not title:
            return None
    if found_unfinished and not version_tag:
        version_tag = "Unfinished"
    return title, version_tag, alt_titles


def _song_notes(row: list[_Cell], col_map: dict[str, int], notes_cell: _Cell) -> tuple[str | None, list[str], list]:
    """(notes, OG filenames, samples). The OG lines leave the notes so clients don't
    render the filenames twice."""
    notes_text = notes_cell.text.strip() if notes_cell.text else None
    og_filenames = extract_og_filenames(notes_text) if notes_text else []
    samples = extract_samples(notes_text) if notes_text else []
    if og_filenames and notes_text:
        notes_text = strip_og_filename_lines(notes_text) or None
    # Dedicated File Name / Instrumental Name column: column values lead, notes-derived
    # names follow (docs/decisions.md::parser.py — dedicated credit and filename columns).
    og_col_text = _get_cell_text(row, col_map.get("og_filename_col", -1))
    if og_col_text:
        col_names = [ln.strip() for ln in og_col_text.split("\n") if ln.strip()]
        og_filenames = col_names + [n for n in og_filenames if n not in col_names]
    return notes_text, og_filenames, samples


def _song_sources(row: list[_Cell], sources_idx: int | None, has_link_column: bool) -> tuple[list[SourceRef], list[str]]:
    """Sources column (Travis Scott): labeled evidence links, kept apart from listen
    links; each URL pairs with its text line (link_lines, as for notices).

    Returns (sources, listen links). With no link column, "Source" is the link column
    (docs/decisions.md::parser.py::sources-as-links)."""
    sources: list[SourceRef] = []
    listen: list[str] = []
    if sources_idx is None:
        return sources, listen
    src_cell = _get_cell(row, sources_idx)
    src_lines = src_cell.text.split("\n")
    for link_idx, link in enumerate(src_cell.links):
        line_num = src_cell.link_lines[link_idx] if link_idx < len(src_cell.link_lines) else -1
        label = src_lines[line_num].strip() if 0 <= line_num < len(src_lines) else ""
        for cleaned in _split_links(link):
            if not has_link_column and resolve_stream_url(cleaned):
                listen.append(cleaned)
            else:
                sources.append(SourceRef(label=label, url=cleaned))
    return sources, listen


def _song_availability(row: list[_Cell], col_map: dict[str, int]) -> tuple[str, str, bool | None, int | None]:
    """(availability, quality, streaming, rating)."""
    avail_text = _get_cell_text(row, col_map.get("available_length", -1))
    quality_text = _get_cell_text(row, col_map.get("quality", -1))
    streaming_text = _get_cell_text(row, col_map.get("streaming", -1)).strip().lower()
    rating = None
    if avail_text and "quality" not in col_map:
        # Travis-style trackers fold quality (and a fan star rating) into the
        # availability cell: 'Full - HQ (Unofficial)\n⭐⭐⭐⭐☆'.
        avail_text, split_quality, rating = _split_compound_availability(avail_text)
        quality_text = split_quality or ""
    return avail_text, quality_text, {"yes": True, "no": False}.get(streaming_text), rating


def _song_links(row: list[_Cell], col_map: dict[str, int], notes_cell: _Cell, source_listen: list[str]) -> list[str]:
    """The links cell, alternate links cell, Sources listen links and the notes cell,
    merged in that order without duplicates."""
    def column_links(key: str) -> list[str]:
        idx = col_map.get(key)
        return _extract_links_from_cell(_get_cell(row, idx)) if idx is not None else []

    return list(dict.fromkeys(
        column_links("links") + column_links("alt_links") + source_listen + _extract_links_from_cell(notes_cell)
    ))


def _move_unplayable_to_sources(links: list[str], sources: list[SourceRef]) -> list[str]:
    """On a no-audio row only what /stream cannot play is evidence
    (docs/decisions.md::parser.py::sources-as-links): those links join `sources`."""
    known = {s.url for s in sources}
    playable = {u: _playable_no_audio(u) for u in links}
    sources += [SourceRef(url=u) for u in links if u not in known and not playable[u]]
    return [u for u in links if playable[u]]


def _parse_song_row(row: list[_Cell], col_map: dict[str, int]) -> SongVersion | None:
    """Parse a song data row into a SongVersion."""
    raw_name = _get_cell_text(row, col_map.get("name", 1))
    if not raw_name:
        return None

    badge, after_badge = extract_badge(raw_name)
    # Parse credits and alt titles from the multi-line name
    song_credits = parse_song_credits(after_badge)
    named = _song_title(after_badge, song_credits.title, song_credits.alt_titles)
    if named is None:
        return None
    title, version_tag, alt_titles = named

    notes_cell = _get_cell(row, col_map.get("notes", 2))
    notes_text, og_filenames, samples = _song_notes(row, col_map, notes_cell)

    # Dedicated credit columns: a Producer column fills producers only when inline
    # '(prod. …)' didn't; Artist columns are the performer, NOT a feature (same entry).
    producers = song_credits.producers or _opt_col(row, col_map, "producers_col")

    sources, source_listen = _song_sources(row, col_map.get("sources"), "links" in col_map)
    merged_links = _song_links(row, col_map, notes_cell, source_listen)
    avail_text, quality_text, streaming, rating = _song_availability(row, col_map)
    if _has_no_audio(avail_text, quality_text):
        merged_links = _move_unplayable_to_sources(merged_links, sources)

    return SongVersion(
        name=title,
        version_tag=version_tag,
        badge=badge,
        featuring=song_credits.featuring,
        producers=producers,
        credited_artists=_opt_col(row, col_map, "credited_artists"),
        engineer=_opt_col(row, col_map, "engineer"),
        collaboration=song_credits.collaboration,
        refs=song_credits.refs,
        director=song_credits.director,
        alt_titles=alt_titles,
        notes=notes_text,
        og_filename=og_filenames[0] if og_filenames else None,
        og_filenames=og_filenames,
        samples=samples,
        sources=sources,
        track_length=_opt_col(row, col_map, "track_length"),
        file_date=_opt_col(row, col_map, "file_date"),
        leak_date=_opt_col(row, col_map, "leak_date"),
        available_length=avail_text or None,
        quality=quality_text or None,
        streaming=streaming,
        rating=rating,
        links=merged_links,
        date_of_recording=_opt_col(row, col_map, "date_of_recording"),
        recording_location=_opt_col(row, col_map, "recording_location"),
        preview_date=_opt_col(row, col_map, "preview_date"),
        type=_opt_col(row, col_map, "type"),
    )


_NO_AUDIO_AVAILABILITY = frozenset({"rumored", "rumoured", "confirmed"})


def _has_no_audio(avail_text: str, quality_text: str) -> bool:
    """True for a row whose audio never leaked: rumoured, confirmed, not available."""
    return (
        avail_text.strip().lower() in _NO_AUDIO_AVAILABILITY
        or quality_text.strip().lower() == "not available"
    )


_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|heic|bmp)(?:$|[?#])", re.I)


def _playable_no_audio(url: str) -> bool:
    """True for a link on a no-audio row that is still worth Play: streamable, not an image."""
    stream = resolve_stream_url(url)
    # imgur.gg is the image host there; its ids carry no extension.
    return bool(stream) and not stream.startswith("https://imgur.gg/") and not _IMAGE_EXT_RE.search(url)


# Base names that mark an UNKNOWN song: distinct mystery tracks, never grouped
# as versions of one song.
_PLACEHOLDER_BASE_NAMES = frozenset({"???", "??", "?", "unknown", "untitled", "tba", "n/a"})


def _sort_era_versions(era: Era) -> None:
    """Order every song's versions by tag family, then number, then sheet order.

    The sort is stable, so untagged and unrecognised versions keep their original
    relative position at the end.
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

    Versions group by ``song_key`` (version tags, case and punctuation ignored),
    even across sections: see docs/decisions.md::parser.py::_reconcile_title_misreads.
    New songs are added to the last (current) section. ``song_index`` maps
    (id(era), key) → Song for O(1) grouping.

    Placeholder names ("???", "Unknown", …) group by a fan-made alt title when one
    exists; without one each row is its own standalone Song.
    """
    if not era.sections:
        era.sections.append(Section())

    _, base_name = extract_version_tag(version.name)
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

    song_key = _song_match_key(base_key)
    # A name of pure punctuation has an empty key; fall back to the exact text
    # rather than lumping every such row into one song.
    key = (id(era), song_key or base_key)
    song = song_index.get(key)
    if song is not None:
        song.versions.append(version)
        return

    # Create new song in the last (current) section
    song = Song(
        base_name=base_key,
        song_key=song_key,
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

    Row emoji wins (🏆 grail vs 🏅/🥇/🥉 wanted), then the block's separator
    label, then the tab's own kind: see docs/decisions.md::parser.py::apply_badge_tabs.
    """
    badge, _ = extract_badge(entry.name)
    if badge is not None:
        return badge
    labelled = _BADGE_BY_SECTION_LABEL.get(entry.section.strip().lower())
    if labelled is not None:
        return labelled
    return tab_default


def _badge_target(song: Song, entry_tag: str | None) -> SongVersion:
    """The version a highlight-tab row is talking about.

    Highlight tabs name a specific take ("⭐ Gotta Pose [V1]"), so match the tag;
    fall back to the first version when the row has no tag, or one this song lacks.
    """
    if entry_tag:
        wanted = entry_tag.strip().lower()
        for version in song.versions:
            if (version.version_tag or "").strip().lower() == wanted:
                return version
    return song.versions[0]


def apply_badge_tabs(
    artist: Artist, tabs: list[tuple[str, list[MiscEntry]]]
) -> int:
    """Stamp badges from every highlight tab onto matching main-tab songs.

    Builds the song index ONCE for all tabs. Matches era-scoped first, then by name
    alone when the song key is unique across the tracker. Placeholder tracks are
    never targets, and already-badged songs are left alone. Both sides drop a
    leading badge emoji before keying. Returns the number of songs annotated.
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
            entry_tag, base_name = extract_version_tag(entry_name)
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
            _badge_target(song, entry_tag).badge = _badge_for_entry(entry, tab_default)
            applied += 1
    return applied


# ---------------------------------------------------------------------------
# Misc / Music Videos tab parsing — secondary tabs, kept separate from eras
# ---------------------------------------------------------------------------

# Local alias map — deliberately separate from COLUMN_ALIASES so these tabs'
# quirks ("Media Length", "Streaming") never perturb main-tab detection.
_MISC_COLUMN_ALIASES = {
    "era": "era",
    # Carti's Released tab has BOTH "Rel. Era" and "Rec. Era": the first in header order
    # (release era) wins; the `not in candidate` guard below ignores the second.
    "rel. era": "era",
    "rec. era": "era",
    "name": "name",
    "title": "name",  # Stems tabs (Travis) use "Title"
    "notes": "notes",
    "length": "length",
    "media length": "length",
    "track length": "length",
    "full length": "length",  # Ye Stems
    "image / length": "length",  # Ye Misc
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

# Era header rows carry per-era stats in the era column ("3 Released 0 Unreleased").
# The lookbehind keeps a long digit run linear, as in _STAT_PAIR_RE.
_MISC_ERA_STATS_RE = re.compile(
    r"(?<!\d)\d+\s+(?:Released|Unreleased|BTS|On\s+Streaming|Full|Snippet)", re.IGNORECASE
)

# Shape-based stats cell match — see docs/decisions.md::parser.py::_STATS_LIKE_ERA_RE
_STATS_LIKE_ERA_RE = re.compile(r"^\s*\d+\s+\S")


def _misc_header_key(text: str) -> str:
    key = text.strip()
    paren = key.find("(")
    if paren > 0:
        key = key[:paren]
    # "Link(s)" — the paren is part of the name, keep a special case
    if text.strip().lower().startswith("link"):
        key = "links"
    # Colon-suffixed headers ("Era:", "Type:"): strip like detect_columns does.
    return re.sub(r"\s+", " ", key.strip().lower()).rstrip(":").strip()


# A date (or length) cell is short and carries a digit. Some Misc-tab era headers put
# the era DESCRIPTION in the `date` column, which must not read as track data.
_MAX_DATE_LEN = 40


def _looks_like_date(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    return len(stripped) <= _MAX_DATE_LEN and any(c.isdigit() for c in stripped)


def _looks_like_section_label(text: str) -> bool:
    """A sub-section name ("Instrumentals"), not an instruction line an editor
    left in the column ("<-- not at all available means…")."""
    return len(text) <= 40 and not text.startswith(("<", "-", "*")) and not text.endswith((".", ":"))


def _misc_header(rows: list[list[_Cell]]) -> tuple[int, dict[str, int]]:
    """The header row of a content tab: needs a name column plus era, links or date."""
    for idx, row in enumerate(rows[: _MAX_HEADER_SCAN_ROWS]):
        candidate: dict[str, int] = {}
        for c_idx, cell in enumerate(row):
            canonical = _MISC_COLUMN_ALIASES.get(_misc_header_key(cell.text))
            if canonical and canonical not in candidate:
                candidate[canonical] = c_idx
        # A name column plus any second content signal qualifies — "date"
        # covers Stems layouts that have neither an Era nor a Links header.
        if "name" in candidate and ("era" in candidate or "links" in candidate or "date" in candidate):
            return idx, candidate
    return -1, {}


def _misc_cell_text(row: list[_Cell], col_map: dict[str, int], field: str) -> str:
    idx = col_map.get(field, -1)
    if idx < 0 or idx >= len(row):
        return ""
    return row[idx].text.strip()


def _misc_known_eras(
    rows: list[list[_Cell]], header_idx: int, col_map: dict[str, int], artist_eras: Iterable[str]
) -> set[str]:
    """Every value the era column uses: a title naming one is a header for the rows
    that follow (the empty-era-cell header style), no keyword list needed."""
    known: set[str] = {k for k in map(_era_match_key, artist_eras) if k}
    era_col = col_map.get("era", -1)
    if era_col < 0:
        return known
    for row in rows[header_idx + 1:]:
        if era_col < len(row):
            key = _era_match_key(row[era_col].text.split("\n")[0].strip())
            if key:
                known.add(key)
    return known


def _misc_links(row: list[_Cell], col_map: dict[str, int]) -> list[str]:
    """Parsed <a href> targets, else URL-ish text."""
    links_idx = col_map.get("links", -1)
    if not 0 <= links_idx < len(row):
        return []
    cell = row[links_idx]
    links = [l for raw in cell.links for l in _split_links(raw)]
    if not links:
        text = cell.text.strip()
        if text.startswith(("http://", "https://")):
            links = _split_links(text)
    return [l for l in links if l]


def _misc_optional(field: str, val: str) -> str | None:
    if field == "date" and not _looks_like_date(val):
        return None
    # A length carries a digit ("3:14") or is a tiny placeholder ("?:??", "N/A", "-");
    # era header rows put a description in Full Length instead.
    if field == "length" and not (_looks_like_date(val) or (val and len(val) <= 5)):
        return None
    return val or None


class _MiscWalk:
    """The row walk of `parse_misc_tab`: era headers, section labels and entries."""

    def __init__(self, kind: str, col_map: dict[str, int], known_eras: set[str]):
        self.kind = kind
        self.col_map = col_map
        self.known_eras = known_eras
        # Only highlight tabs carry block separators; elsewhere a lone "Special"
        # cell is an entry, not a label.
        self.is_badge_tab = kind in _BADGE_BY_TAB_KIND
        self.entries: list[MiscEntry] = []
        self.current_era = ""
        self.current_section = ""

    def _text(self, row: list[_Cell], field: str) -> str:
        return _misc_cell_text(row, self.col_map, field)

    def _set_era(self, era: str) -> None:
        # A content tab's sub-sections belong to one era. Badge-tab blocks
        # (Grails / Wanted) span eras, so theirs carry over.
        if era != self.current_era and not self.is_badge_tab:
            self.current_section = ""
        self.current_era = era

    def row(self, row: list[_Cell]) -> None:
        if all(not c.text.strip() for c in row) or self._badge_separator(row):
            return
        era_text = self._text(row, "era")
        name = self._text(row, "name")
        # Era header row: stats text in the era column, era name in the name
        # column (mirrors the main tab's grammar).
        if era_text and _MISC_ERA_STATS_RE.search(era_text):
            if name:
                self._set_era(name.split("\n")[0].strip())
            return
        if name:
            self._named_row(row, era_text, name)

    def _badge_separator(self, row: list[_Cell]) -> bool:
        """Grails/Wanted section separator — see docs/decisions.md::parser.py::grails-wanted-separator"""
        if not self.is_badge_tab:
            return False
        lone = [c.text.strip() for c in row if c.text.strip()]
        if len(lone) != 1:
            return False
        _, label = extract_badge(lone[0])
        if label.lower() not in BADGE_SECTION_LABELS:
            return False
        self.current_section = label
        return True

    def _named_row(self, row: list[_Cell], era_text: str, name: str) -> None:
        first_line = name.split("\n")[0].strip()
        name_key = _era_match_key(first_line)
        era_key = _era_match_key(era_text.split("\n")[0].strip()) if era_text else ""
        if era_text:
            self._set_era(era_text.split("\n")[0].strip())
        entry = self._entry(row, first_line)
        # Structural-row detection — see docs/decisions.md::parser.py::badge-tab-structural-rows
        has_track_data = any((
            entry.date, entry.length,
            entry.available, entry.quality, entry.links,
        )) or entry.streaming is not None
        # Two more era-header shapes — see docs/decisions.md::parser.py::badge-tab-structural-rows
        stats_era = bool(_STATS_LIKE_ERA_RE.match(era_text))
        if (
            name_key and name_key in self.known_eras and name_key != era_key
            and (stats_era or (not era_text and not has_track_data))
        ):
            self._set_era(first_line)
            return
        # Bare label rows: docs/decisions.md::parser.py::badge-tab-structural-rows. A divider
        # keyword with no track data is a label even with an aside (Travis's "Project" rows).
        if not has_track_data and (
            (not entry.notes and not entry.entry_type) or first_line.lower() in SECTION_SEPARATORS
        ):
            if not self.is_badge_tab and _looks_like_section_label(first_line):
                self.current_section = first_line
            return
        self.entries.append(entry)

    def _entry(self, row: list[_Cell], first_line: str) -> MiscEntry:
        def opt(field: str) -> str | None:
            return _misc_optional(field, self._text(row, field))

        return MiscEntry(
            era_name=self.current_era,
            row_index=len(self.entries),
            section=self.current_section,
            name=first_line,
            notes=opt("notes"),
            entry_type=opt("entry_type"),
            date=opt("date"),
            length=opt("length"),
            available=opt("available"),
            quality=opt("quality"),
            streaming={"yes": True, "no": False}.get(self._text(row, "streaming").lower()),
            links=_misc_links(row, self.col_map),
            source_tab=self.kind,
        )


def parse_misc_tab(
    html: str | list[list[_Cell]], kind: str, artist_eras: Iterable[str] = ()
) -> list[MiscEntry]:
    """Parse a Misc or Music Videos tab (htmlview HTML, or rows from extract_grid) into MiscEntry rows.

    ``kind`` is ``"misc"`` or ``"music_videos"`` and is stamped on each entry
    as ``source_tab``. ``artist_eras`` are the main tab's era names, used to
    recognise header rows — a tab's own era column often abbreviates them
    ("Birds" where the header reads "Birds In The Trap Sing McKnight"). Rows
    keep the literal era label from their era column (or the last era header);
    no fuzzy matching against main-tab eras.
    """
    rows = extract_table(html) if isinstance(html, str) else html
    if not rows:
        return []
    header_idx, col_map = _misc_header(rows)
    if header_idx < 0:
        return []
    walk = _MiscWalk(kind, col_map, _misc_known_eras(rows, header_idx, col_map, artist_eras))
    for row in rows[header_idx + 1:]:
        walk.row(row)
    return walk.entries


# ---------------------------------------------------------------------------
# Art tab parsing — high-quality era artwork
# ---------------------------------------------------------------------------

# Art-tab header labels. The tab has its own layout (no Name/Links columns),
# so it gets its own tiny header detection rather than COLUMN_ALIASES.
_ART_ERA_HEADERS = frozenset({"era", "album", "project", "era/project"})
# Ordered best-first, NOT a set: "Project Type" (the role) must beat "Art Type" (the
# medium). See docs/decisions.md::parser.py::art-type-column-priority.
_ART_TYPE_HEADERS = ("project type", "type", "image type", "category", "art type")


class ArtMap(dict):
    """era match key -> cover URL, remembering which keys are stand-ins.

    A *synthetic* key is a version-stripped alias ("donda" for "Donda [V1]"). It
    names one version's cover, so it must never serve a DIFFERENT version (see
    _era_art_candidate).
    """

    __slots__ = ("synthetic",)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.synthetic: set[str] = set()


def _art_header_columns(row: list[_Cell]) -> tuple[int | None, int | None]:
    """(Era column, best-ranked Project Type column) of one candidate header row."""
    era_idx = type_idx = None
    type_rank = len(_ART_TYPE_HEADERS)
    for c_idx, cell in enumerate(row):
        key = re.sub(r"\s+", " ", cell.text.strip().lower()).rstrip(":").strip()
        if era_idx is None and key in _ART_ERA_HEADERS:
            era_idx = c_idx
        # Best-ranked header wins, not the leftmost one.
        rank = _ART_TYPE_HEADERS.index(key) if key in _ART_TYPE_HEADERS else type_rank
        if rank < type_rank:
            type_rank, type_idx = rank, c_idx
    return era_idx, type_idx


def _art_tab_columns(rows: list[list[_Cell]]) -> tuple[int | None, int | None, int]:
    """Locate the Era and Project Type columns and the first data row.

    Returns ``(era_idx, type_idx, start_row)``. Either index may be None on
    art tabs that have no header row — callers fall back to scanning the
    whole row, which is what this function exists to avoid.
    """
    for idx, row in enumerate(rows[:5]):
        if any(cell.images for cell in row):
            break  # already into the data; no header row above it
        era_idx, type_idx = _art_header_columns(row)
        if era_idx is not None or type_idx is not None:
            return era_idx, type_idx, idx + 1
    start = 1 if rows and not any(cell.images for cell in rows[0]) else 0
    return None, None, start


class _ArtCollector:
    """Per-era images of an Art tab: the cover-labelled one and the first one seen."""

    def __init__(self, era_idx: int | None, type_idx: int | None):
        self.era_idx = era_idx
        self.type_idx = type_idx
        # {era_key: {"cover": url, "first": url}}
        self.era_info: dict[str, dict[str, str | None]] = {}
        # Version-stripped key → the FIRST versioned key filed under it, so an era
        # the Art tab spells without a version tag still resolves.
        self.base_keys: dict[str, str] = {}
        # Art tabs leave the era cell blank on an era's continuation rows, so the last
        # seen era carries forward (the first text cell is the artwork's own name).
        self.last_era_name = ""

    def _era_name(self, row: list[_Cell]) -> str:
        if self.era_idx is not None:
            return _get_cell_text(row, self.era_idx).strip() or self.last_era_name
        # No Era header — fall back to the first non-empty text cell.
        return next((cell.text.strip() for cell in row if cell.text.strip()), "")

    def add(self, row: list[_Cell]) -> None:
        # First image found in the row is the candidate
        img_url = next((cell.images[0] for cell in row if cell.images), None)
        era_name = self._era_name(row) if img_url else ""
        if not era_name:
            return
        self.last_era_name = era_name
        # Version-aware: the Art tab lists each version's own cover, so
        # "Donda [V2]" must not collapse onto "Donda [V1]".
        key = _era_match_key(era_name, keep_discriminators=True)
        if not key:
            return
        self.base_keys.setdefault(_era_match_key(era_name), key)
        info = self.era_info.setdefault(key, {"cover": None, "first": None})
        if info["first"] is None:
            info["first"] = img_url
        if self.type_idx is not None:
            cover_text = _get_cell_text(row, self.type_idx)
        else:
            cover_text = " ".join(c.text.strip() for c in row if c.text.strip())
        if info["cover"] is None and _COVER_RE.search(cover_text):
            info["cover"] = img_url

    def result(self, source_url: str | None) -> "ArtMap":
        # Prefer the cover-labelled image, fall back to the first image
        result = ArtMap()
        for key, info in self.era_info.items():
            chosen = info["cover"] or info["first"]
            if chosen and source_url and not urlparse(chosen).netloc:
                chosen = urljoin(source_url, chosen)
            if chosen:
                result[key] = chosen
        # Also file each entry under its version-stripped key (first versioned entry wins),
        # marked synthetic: see docs/decisions.md::parser.py::art-version-keys.
        for base, versioned in self.base_keys.items():
            if base not in result and versioned in result:
                result[base] = result[versioned]
                result.synthetic.add(base)
        return result


def parse_art_tab(html: str, source_url: str | None = None) -> dict[str, str]:
    """Parse an Art tab HTML export → {era_match_key: image_url} mapping.

    *source_url* resolves relative image sources, as in parse_sheet: the fetcher
    compares these URLs against parse_sheet's already-resolved covers.

    Prefers an image whose **Project Type** column says "cover" (see
    docs/decisions.md::parser.py::art-cover-column), else the era's first image.
    Returns a dict keyed by the normalised era match key (lowercase, stripped).
    """
    rows = extract_table(html)
    if not rows:
        return {}
    era_idx, type_idx, start = _art_tab_columns(rows)
    collector = _ArtCollector(era_idx, type_idx)
    for row in rows[start:]:
        if row:
            collector.add(row)
    return collector.result(source_url)


def art_tab_candidates(artist: Artist, art_map: dict[str, str]) -> dict[str, str]:
    """{era name: Art-tab image} for eras whose main-tab cover it might upgrade.

    Only a candidate: the Art tab can hold a single's or a sibling era's art under
    the same name, so the fetcher adopts one only when it is the same picture as the
    main-tab cover (docs/decisions.md::fetcher.py::art-tab-identity). An era without
    a main-tab cover has nothing to compare against and gets no candidate.
    """
    candidates = {}
    for era in artist.eras:
        url = _era_art_candidate(era, art_map) if era.art_url else None
        if url and url != era.art_url:
            candidates[era.name] = url
    return candidates


def _era_art_candidate(era: Era, art_map: dict[str, str]) -> str | None:
    """The Art-tab image filed under *era*'s version-aware key, else its stripped key.

    A SYNTHETIC stripped key is a sibling version's cover, so it never stands in for
    a versioned era.
    """
    synthetic = getattr(art_map, "synthetic", frozenset())
    for name in (era.name, *era.alt_names):
        exact = _era_match_key(name, keep_discriminators=True)
        if exact and exact in art_map:
            return art_map[exact]
        stripped = _era_match_key(name)
        if not stripped or stripped not in art_map:
            continue
        if stripped in synthetic and VERSION_TAG_PATTERN.search(name):
            continue
        return art_map[stripped]
    return None


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
# ArtistGrid registry, served as CSV (https://artists.artistgrid.cx/artists.csv)
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
    for row in csv.DictReader(io.StringIO(csv_text, newline="")):
        name = (row.get("name") or "").strip()
        raw_url = (row.get("url") or "").strip()
        if not name or not raw_url:
            continue
        if re.match(r"https?://", raw_url, re.IGNORECASE):
            url = raw_url
        elif "." in raw_url:
            url = f"https://{raw_url}/"
        else:
            url = f"https://docs.google.com/spreadsheets/d/{raw_url}/edit"
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
