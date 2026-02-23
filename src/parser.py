"""LeakSheet — HTML parser for Google Sheets tracker exports.

Parses the htmlview export of a Google Spreadsheet music tracker into
structured Artist/Era/Song/SongVersion objects.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from src.config import COLUMN_ALIASES
from src.models import (
    Artist,
    Era,
    Song,
    SongVersion,
    VERSION_TAG_PATTERN,
    extract_badge,
    extract_version_tag,
    slugify,
)


# ---------------------------------------------------------------------------
# Low-level HTML table extraction
# ---------------------------------------------------------------------------

class _TableExtractor(HTMLParser):
    """Extract rows from the first <table> in a Google Sheets HTML export.

    Each row is a list of _Cell objects containing text, links, and CSS class.
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
        self._cell_class = ""
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
            self._cell_class = a.get("class", "")
            self._colspan = int(a.get("colspan", "1"))
        elif tag == "a" and self.in_td:
            self.in_a = True
            self._a_href = a.get("href", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.in_a:
            self.in_a = False
            if self._a_href:
                self._cell_links.append(self._a_href)
            self._a_href = ""
        elif tag == "td" and self.in_td:
            self.in_td = False
            cell = _Cell(
                text=self._cell_text.strip(),
                links=list(self._cell_links),
                css_class=self._cell_class,
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
    """A single table cell with text content, extracted links, and CSS class."""
    __slots__ = ("text", "links", "css_class")

    def __init__(
        self,
        text: str = "",
        links: list[str] | None = None,
        css_class: str = "",
    ) -> None:
        self.text = text
        self.links = links or []
        self.css_class = css_class

    def __repr__(self) -> str:
        if self.links:
            return f"Cell({self.text!r}, links={len(self.links)})"
        return f"Cell({self.text!r})"


def extract_table(html_content: str) -> list[list[_Cell]]:
    """Parse HTML and return all table rows as lists of _Cell."""
    parser = _TableExtractor()
    parser.feed(html_content)
    return parser.rows


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

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

        canonical = COLUMN_ALIASES.get(key)

        # If no match, try matching against known aliases as prefixes
        # (handles cases like "NotesWelcome to..." where extra text is glued on)
        if not canonical:
            for alias, canon in COLUMN_ALIASES.items():
                if key.startswith(alias) and len(alias) > 2:
                    canonical = canon
                    break

        if canonical and canonical not in col_map:
            col_map[canonical] = idx

    return col_map


# ---------------------------------------------------------------------------
# Row classification
# ---------------------------------------------------------------------------

# Pattern for era stats rows, e.g. "0 OG File(s)1 Full0 Tagged2 Partial..."
# or "1 Total Full0 OG File0 Partial / Cut0 Snippet3 Unavailable" (Carti)
ERA_STATS_PATTERN = re.compile(
    r"\d+\s+(OG File|Total Full|Full|Tagged|Partial|Snippet|Stem|Unavailable)",
    re.IGNORECASE,
)

# Section separators (Carti-specific rows with just a category label)
SECTION_SEPARATORS = {
    "surfaced", "unsurfaced", "unavailable",
    "og files for released songs & alternate versions",
    "unknown collaborations",
}


def _is_era_header(row: list[_Cell]) -> bool:
    """Check if a row is an era header (contains stats pattern in first cell)."""
    if not row:
        return False
    return bool(ERA_STATS_PATTERN.search(row[0].text))


def _is_section_separator(row: list[_Cell]) -> bool:
    """Check if a row is a Carti-style section separator."""
    # Usually a row where most cells are empty and one contains a separator keyword
    non_empty = [c for c in row if c.text.strip()]
    if len(non_empty) <= 2:
        for cell in non_empty:
            if cell.text.strip().lower() in SECTION_SEPARATORS:
                return True
    return False


def _is_empty_row(row: list[_Cell]) -> bool:
    """Check if all cells in a row are empty."""
    return all(not c.text.strip() for c in row)


def _era_match_key(full_era_name: str) -> str:
    """Extract the matching key from an era name, lowercased for matching.

    Era headers contain full names like "Before Baby Keem(as Hykeem Carter...)"
    but song rows only use "Before Baby Keem".  We extract the text before
    the first '(' that is directly glued to the previous word (no space),
    strip any version tags [V1]/[V2], and lowercase for case-insensitive matching.

    Examples:
    - "Before Baby Keem(as Hykeem Carter...)" → "before baby keem"
    - "Ca$ino(Child With Wolves, Janice)" → "ca$ino"  (matches "CA$INO")
    - "Tu Pimp A Caterpillar [V1](...)" → "tu pimp a caterpillar"
    - "THC: The High Chronical$" → "thc: the high chronical$"
    """
    key = full_era_name
    # Strip from first '(' onward
    paren_idx = key.find("(")
    if paren_idx > 0:
        key = key[:paren_idx]
    key = key.strip()
    # Strip version tags like [V1], [V2], [V3]
    key = VERSION_TAG_PATTERN.sub("", key).strip()
    return key.lower()


# ---------------------------------------------------------------------------
# Link cleanup
# ---------------------------------------------------------------------------

def _clean_link(url: str) -> str:
    """Strip Google redirect wrapper from URLs.

    Google Sheets wraps links as: https://www.google.com/url?q=REAL_URL&...
    """
    if "google.com/url" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "q" in qs:
            return qs["q"][0]
    return url


def _extract_links_from_cell(cell: _Cell) -> list[str]:
    """Get cleaned links from a cell."""
    return [_clean_link(link) for link in cell.links if link]


# ---------------------------------------------------------------------------
# High-level parser
# ---------------------------------------------------------------------------

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


def parse_sheet(html_content: str, artist_name: str) -> Artist:
    """Parse a Google Sheets HTML export into an Artist model.

    This is the main entry point for parsing a single tracker.
    """
    rows = extract_table(html_content)
    if not rows:
        return Artist(name=artist_name, slug=slugify(artist_name), eras=[])

    # Step 1: detect column layout from header row
    col_map = detect_columns(rows[0])

    # Step 2: walk rows, classify and extract
    eras: list[Era] = []
    current_era: Optional[Era] = None
    # Map from lowercased era matching key → Era object.
    # Keys are lowercase, parenthetical-stripped, version-tag-stripped.
    era_by_key: dict[str, Era] = {}

    for row_idx, row in enumerate(rows):
        # Skip header row
        if row_idx == 0:
            continue

        # Skip empty rows
        if _is_empty_row(row):
            continue

        # Skip section separators
        if _is_section_separator(row):
            continue

        # Check for era header
        if _is_era_header(row):
            era_name_col = col_map.get("name", 1)
            notes_col = col_map.get("notes", 2)

            era_name_full = _get_cell_text(row, era_name_col)
            era_desc = _get_cell_text(row, notes_col)
            era_stats = _get_cell_text(row, 0)

            if era_name_full:
                era_key = _era_match_key(era_name_full)

                current_era = Era(
                    name=era_name_full,
                    description=era_desc if era_desc else None,
                    stats_raw=era_stats if era_stats else None,
                )
                eras.append(current_era)
                era_by_key[era_key] = current_era
            continue

        # Check for song row: first cell should match a known era key
        era_col = col_map.get("era", 0)
        row_era = _get_cell_text(row, era_col)

        if row_era:
            # Case-insensitive lookup
            row_era_lower = row_era.lower()
            matched_era = era_by_key.get(row_era_lower)
            if matched_era is not None:
                current_era = matched_era
                version = _parse_song_row(row, col_map)
                if version:
                    _add_version_to_era(current_era, version)
                continue

            # Fallback: assign to current_era if set (handles abbreviated
            # era names like "Digital Nas Collab" vs "Collaboration with Digital Nas")
            if current_era is not None:
                version = _parse_song_row(row, col_map)
                if version:
                    _add_version_to_era(current_era, version)
                continue

        # If the first cell is non-empty but doesn't match an era,
        # and we have no current_era context, skip it.

    return Artist(
        name=artist_name,
        slug=slugify(artist_name),
        eras=eras,
    )


def _parse_song_row(row: list[_Cell], col_map: dict[str, int]) -> Optional[SongVersion]:
    """Parse a song data row into a SongVersion."""
    name_idx = col_map.get("name", 1)
    raw_name = _get_cell_text(row, name_idx)

    if not raw_name:
        return None

    # Extract badge emoji
    badge, clean_name = extract_badge(raw_name)

    # Extract version tag
    version_tag, _base = extract_version_tag(clean_name)

    # Build the version object
    notes_idx = col_map.get("notes", 2)
    notes_cell = _get_cell(row, notes_idx)

    links_idx = col_map.get("links")
    link_cell = _get_cell(row, links_idx) if links_idx is not None else _Cell()
    # Collect links from both the dedicated links cell and the notes cell,
    # merging them while preserving order and removing duplicates.
    all_links = _extract_links_from_cell(link_cell)
    note_links = _extract_links_from_cell(notes_cell)
    seen: set[str] = set()
    merged_links: list[str] = []
    for lnk in all_links + note_links:
        if lnk not in seen:
            seen.add(lnk)
            merged_links.append(lnk)

    version = SongVersion(
        name=clean_name,
        version_tag=version_tag,
        badge=badge,
        notes=notes_cell.text if notes_cell.text else None,
        track_length=_get_cell_text(row, col_map.get("track_length", -1)) or None,
        file_date=_get_cell_text(row, col_map.get("file_date", -1)) or None,
        leak_date=_get_cell_text(row, col_map.get("leak_date", -1)) or None,
        available_length=_get_cell_text(row, col_map.get("available_length", -1)) or None,
        quality=_get_cell_text(row, col_map.get("quality", -1)) or None,
        links=merged_links,
        date_of_recording=_get_cell_text(row, col_map.get("date_of_recording", -1)) or None,
        type=_get_cell_text(row, col_map.get("type", -1)) or None,
    )

    return version


def _add_version_to_era(era: Era, version: SongVersion) -> None:
    """Add a version to the appropriate Song in the era, creating it if needed.

    Songs with the same base name (ignoring version tags [V1], [V2], etc.) are
    grouped together.
    """
    _, base_name = extract_version_tag(version.name)
    # Also strip any sub-info in parens for grouping
    # But keep the base_name as-is for matching — only strip version tags
    base_key = base_name.strip()

    # Look for an existing song with matching base name
    for song in era.songs:
        if song.base_name == base_key:
            song.versions.append(version)
            return

    # Create new song
    song = Song(base_name=base_key, versions=[version])
    era.songs.append(song)


# ---------------------------------------------------------------------------
# File-level convenience
# ---------------------------------------------------------------------------

def parse_file(path: Path | str, artist_name: str) -> Artist:
    """Parse a tracker HTML file into an Artist model."""
    path = Path(path)
    html_content = path.read_text(encoding="utf-8")
    return parse_sheet(html_content, artist_name)


def parse_tracker_directory(trackers_dir: Path | str) -> list[Artist]:
    """Parse all tracker files in a directory.

    Returns a list of Artist models.
    """
    from src.config import discover_trackers

    trackers_dir = Path(trackers_dir)
    artists = []

    for artist_name, sheet_path in discover_trackers(trackers_dir):
        artist = parse_file(sheet_path, artist_name)
        artists.append(artist)

    return artists
