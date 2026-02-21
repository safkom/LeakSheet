"""
Google Spreadsheet HTML parser for leak sheets.

Parses the HTML view of a public Google Spreadsheet and extracts
structured data: artists (sheets), eras (sections), and songs (entries).
"""

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.models import Era, Sheet, Song, SpreadsheetResult

# Known column header names (case-insensitive) and their Song field mappings
COLUMN_MAP = {
    "song name": "name",
    "title": "name",
    "name": "name",
    "version": "version",
    "ver": "version",
    "features": "features",
    "feat": "features",
    "featuring": "features",
    "ft": "features",
    "notes": "notes",
    "note": "notes",
    "comment": "notes",
    "comments": "notes",
    "status": "notes",
    "length": "length",
    "duration": "length",
    "time": "length",
}

# Song model fields (not including "extra")
SONG_FIELDS = {"name", "version", "features", "notes", "length"}

# Minimum number of cells that must be non-empty for a row to be treated as a song
_MIN_SONG_CELLS = 1

# A row is an era header if it has a single visible cell spanning multiple columns
_ERA_MIN_COLSPAN = 2


def extract_spreadsheet_id(url: str) -> Optional[str]:
    """Extract the spreadsheet ID from a Google Sheets URL."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


def build_html_url(spreadsheet_id: str) -> str:
    """Build the HTML view URL for a given spreadsheet ID."""
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/htmlview"


def _cell_text(cell: Tag) -> str:
    """Return stripped text content of a table cell."""
    return cell.get_text(separator=" ", strip=True)


def _is_era_header(row: Tag) -> bool:
    """
    Return True if this row looks like an era/section header.

    Era headers in Google Sheets HTML are rows where all visible content is
    in a single <td> with a large colspan attribute.
    """
    cells = row.find_all("td")
    visible = [c for c in cells if _cell_text(c)]
    if len(visible) != 1:
        return False
    colspan = int(visible[0].get("colspan", 1))
    return colspan >= _ERA_MIN_COLSPAN


def _is_column_header(row: Tag, first_row: bool) -> bool:
    """
    Return True if this row is a column header row.

    We only treat the very first data row as a potential column header row
    when its first cell text matches a known column name.
    """
    if not first_row:
        return False
    cells = row.find_all("td")
    if not cells:
        return False
    first_text = _cell_text(cells[0]).lower()
    return first_text in COLUMN_MAP


def _parse_column_headers(row: Tag) -> list[str]:
    """Return a list of normalised column header strings from a header row."""
    return [_cell_text(c).lower() for c in row.find_all("td")]


def _parse_song(cells: list[Tag], column_headers: list[str]) -> Song:
    """
    Build a Song from a list of <td> cells and the column header mapping.

    When no column headers have been detected the first cell is treated as the
    song name and remaining cells are stored in ``extra``.  Any columns that do
    not map to a known Song field are also stored in ``extra``.
    """
    # If no headers were detected, synthesise default positional headers so
    # that at minimum the first column is recognised as the song name.
    if not column_headers:
        default_fields = ["song name", "version", "features", "notes", "length"]
        effective_headers: list[str] = [
            default_fields[i] if i < len(default_fields) else ""
            for i in range(len(cells))
        ]
    else:
        effective_headers = column_headers

    data: dict = {}
    extra: dict = {}

    for i, cell in enumerate(cells):
        text = _cell_text(cell)
        if i < len(effective_headers):
            header = effective_headers[i]
            field = COLUMN_MAP.get(header)
            if field and field in SONG_FIELDS:
                data[field] = text or None
            else:
                # Unknown column – store in extra using its original header name
                if text:
                    extra[header or f"col_{i}"] = text
        elif text:
            extra[f"col_{i}"] = text

    # Ensure name has a value (may be empty string for blank rows – caller should skip)
    if not data.get("name"):
        data["name"] = ""
    data["extra"] = extra
    return Song(**data)


def _parse_table(table: Tag) -> tuple[list[str], list[Era]]:
    """
    Parse a single <table> element into (column_headers, eras).

    Returns the detected column headers and a list of Era objects.
    """
    rows = table.find_all("tr")
    column_headers: list[str] = []
    eras: list[Era] = []
    current_era: Optional[Era] = None
    first_data_row = True

    for row in rows:
        # Skip <thead> rows (they contain column letters A, B, C…)
        if row.find_parent("thead"):
            continue

        cells = row.find_all("td")
        if not cells:
            continue

        if _is_era_header(row):
            # Single merged cell → era header
            era_name = _cell_text(cells[0])
            current_era = Era(name=era_name)
            eras.append(current_era)
            first_data_row = True  # reset so next row can be column headers
            continue

        if _is_column_header(row, first_data_row):
            column_headers = _parse_column_headers(row)
            first_data_row = False
            continue

        first_data_row = False

        song = _parse_song(cells, column_headers)
        if not song.name:
            # Skip completely blank rows
            continue

        if current_era is None:
            # Songs before any era header go into a generic era
            current_era = Era(name="Unknown Era")
            eras.append(current_era)

        current_era.songs.append(song)

    return column_headers, eras


def _get_sheet_tabs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Return a list of (sheet_name, gid_anchor) pairs from the sheet tab menu.

    Example: [("Drake", "gid=0"), ("Kanye West", "gid=1")]
    """
    tabs: list[tuple[str, str]] = []
    menu = soup.find(id="sheet-menu")
    if not menu:
        return tabs
    for li in menu.find_all("li"):
        a = li.find("a")
        if not a:
            continue
        href = a.get("href", "")
        gid = href.lstrip("#")
        name = a.get_text(strip=True)
        if name and gid:
            tabs.append((name, gid))
    return tabs


def parse_html(html: str, spreadsheet_id: str = "", url: str = "") -> SpreadsheetResult:
    """
    Parse raw HTML from a Google Sheets HTML view export.

    Args:
        html: The full HTML page content.
        spreadsheet_id: The spreadsheet ID (used in the result object).
        url: The original URL (used in the result object).

    Returns:
        A :class:`SpreadsheetResult` containing all sheets, eras and songs.
    """
    soup = BeautifulSoup(html, "lxml")

    tabs = _get_sheet_tabs(soup)
    sheets: list[Sheet] = []

    if tabs:
        for sheet_name, gid in tabs:
            container = soup.find(id=gid)
            if not container:
                continue
            table = container.find("table")
            if not table:
                continue
            _, eras = _parse_table(table)
            sheets.append(Sheet(name=sheet_name, eras=eras))
    else:
        # Fallback: no sheet menu found – parse all tables
        for i, table in enumerate(soup.find_all("table", class_="waffle")):
            _, eras = _parse_table(table)
            sheets.append(Sheet(name=f"Sheet{i + 1}", eras=eras))

    return SpreadsheetResult(
        spreadsheet_id=spreadsheet_id,
        url=url,
        sheets=sheets,
    )
