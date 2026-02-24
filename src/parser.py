"""LeakSheet — HTML parser for Google Sheets tracker exports.

Parses the htmlview export of a Google Spreadsheet music tracker into
structured Artist/Era/Song/SongVersion objects.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.config import COLUMN_ALIASES
from src.models import (
    Artist,
    Era,
    EraStats,
    ParseMetadata,
    Section,
    Song,
    SongVersion,
    TrackerStats,
    VERSION_TAG_PATTERN,
    extract_badge,
    extract_og_filename,
    extract_samples,
    extract_version_tag,
    parse_era_stats,
    parse_highlighted_producers,
    parse_song_credits,
    parse_timeline,
    parse_tracker_stats,
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
        self._cell_images: list[str] = []
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
            self._cell_images = []
            self._cell_class = a.get("class", "")
            self._colspan = int(a.get("colspan", "1"))
        elif tag == "a" and self.in_td:
            self.in_a = True
            self._a_href = a.get("href", "")
        elif tag == "img" and self.in_td:
            src = a.get("src", "")
            if src:
                self._cell_images.append(src)
        elif tag == "br" and self.in_td:
            self._cell_text += "\n"

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
                images=list(self._cell_images),
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
    """A single table cell with text content, extracted links, images, and CSS class."""
    __slots__ = ("text", "links", "images", "css_class")

    def __init__(
        self,
        text: str = "",
        links: list[str] | None = None,
        images: list[str] | None = None,
        css_class: str = "",
    ) -> None:
        self.text = text
        self.links = links or []
        self.images = images or []
        self.css_class = css_class

    def __repr__(self) -> str:
        parts = [f"Cell({self.text!r}"]
        if self.links:
            parts.append(f", links={len(self.links)}")
        if self.images:
            parts.append(f", imgs={len(self.images)}")
        return "".join(parts) + ")"


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


# Keywords that identify the tracker footer section (global stats, changelogs, guidelines).
# Once we hit one of these, we stop parsing songs.
_FOOTER_KEYWORDS = {
    "total links", "total link", "total full",
    "changelogs", "changelog",
    "tracker guidelines",
    "current tracker editors", "editor comments",
}


def _is_tracker_footer(row: list[_Cell]) -> bool:
    """Check if a row belongs to the tracker footer (stats, changelogs, guidelines).

    This prevents footer content from being attributed to the last era.
    """
    for cell in row:
        text_lower = cell.text.strip().lower()
        for keyword in _FOOTER_KEYWORDS:
            if keyword in text_lower:
                return True
    return False


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


def _fuzzy_era_match(key: str, era_by_key: dict[str, Era]) -> Era | None:
    """Fuzzy match a row's era key against known era keys.

    Uses word-overlap scoring. Requires at least 2 shared significant
    words (length > 2) and >= 50% overlap with the smaller word set.

    Handles cases like "Digital Nas Collab" matching
    "Collaboration with Digital Nas".
    """
    key_words = {w for w in key.split() if len(w) > 2}
    if not key_words:
        return None

    best_match: Era | None = None
    best_score = 0.0

    for era_key, era in era_by_key.items():
        era_words = {w for w in era_key.split() if len(w) > 2}
        if not era_words:
            continue
        overlap = len(key_words & era_words)
        min_size = min(len(key_words), len(era_words))
        score = overlap / min_size if min_size > 0 else 0
        if score > best_score and overlap >= 2:
            best_score = score
            best_match = era

    return best_match if best_score >= 0.5 else None


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
    current_era: Era | None = None
    # Map from lowercased era matching key → Era object.
    # Keys are lowercase, parenthetical-stripped, version-tag-stripped.
    era_by_key: dict[str, Era] = {}
    in_footer = False

    # Parse metadata tracking
    total_rows = len(rows) - 1  # exclude header
    song_rows = 0
    skipped_rows = 0
    unmatched_rows: list[str] = []
    footer_rows = 0
    fuzzy_matched_rows = 0

    for row_idx, row in enumerate(rows):
        # Skip header row
        if row_idx == 0:
            continue

        # Skip empty rows
        if _is_empty_row(row):
            continue

        # Section separators → capture as named sections within current era
        if _is_section_separator(row):
            if current_era is not None:
                non_empty = [c for c in row if c.text.strip()]
                label = non_empty[0].text.strip() if non_empty else ""
                if label:
                    current_era.sections.append(Section(name=label))
            continue

        # Check for era header (must come before footer check, since
        # Carti era stats contain "Total Full" which is also a footer keyword).
        # Also resets footer state — if data resumes after a footer-like row,
        # it's a new era, not leftover footer.
        if _is_era_header(row):
            in_footer = False
            era_name_col = col_map.get("name", 1)
            notes_col = col_map.get("notes", 2)

            era_name_full = _get_cell_text(row, era_name_col)
            timeline_raw = _get_cell_text(row, notes_col)
            era_stats_raw = _get_cell_text(row, 0)

            # Extract era art, highlighted producers, and description
            # from cells beyond the timeline column.
            art_url = None
            highlighted_producers: list[str] = []
            desc_candidates: list[str] = []
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

            # Parse timeline events from the timeline cell
            timeline = parse_timeline(timeline_raw) if timeline_raw else []

            # Parse structured stats from raw text
            era_stats = parse_era_stats(era_stats_raw) if era_stats_raw else None

            if era_name_full:
                era_key = _era_match_key(era_name_full)

                current_era = Era(
                    name=era_name_full,
                    description=era_desc if era_desc else None,
                    timeline=timeline,
                    stats_raw=era_stats_raw if era_stats_raw else None,
                    stats=era_stats,
                    art_url=art_url,
                    highlighted_producers=highlighted_producers,
                    sections=[Section()],  # default unnamed section
                )
                eras.append(current_era)
                era_by_key[era_key] = current_era
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

        if row_era:
            # Case-insensitive exact lookup
            row_era_lower = row_era.lower()
            matched_era = era_by_key.get(row_era_lower)

            # Fuzzy match if exact lookup fails
            if matched_era is None:
                matched_era = _fuzzy_era_match(row_era_lower, era_by_key)
                if matched_era is not None:
                    fuzzy_matched_rows += 1

            if matched_era is not None:
                current_era = matched_era
                version = _parse_song_row(row, col_map)
                if version:
                    _add_version_to_era(current_era, version)
                    song_rows += 1
                continue

            # Fallback: assign to current_era if set (handles abbreviated
            # era names that fuzzy matching couldn't resolve)
            if current_era is not None:
                version = _parse_song_row(row, col_map)
                if version:
                    _add_version_to_era(current_era, version)
                    song_rows += 1
                continue

        # Unmatched row — track it for diagnostics
        skipped_rows += 1
        if len(unmatched_rows) < 50:
            row_text = " | ".join(c.text.strip() for c in row if c.text.strip())[:200]
            if row_text:
                unmatched_rows.append(f"Row {row_idx}: {row_text}")

    # Step 3: detect and parse global stats row
    tracker_stats = _find_global_stats(rows)

    # Step 4: build parse metadata
    metadata = ParseMetadata(
        total_rows=total_rows,
        song_rows=song_rows,
        skipped_rows=skipped_rows,
        unmatched_rows=unmatched_rows,
        footer_rows=footer_rows,
        fuzzy_matched_rows=fuzzy_matched_rows,
    )

    return Artist(
        name=artist_name,
        slug=slugify(artist_name),
        eras=eras,
        tracker_stats=tracker_stats,
        parse_metadata=metadata,
    )


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


def _parse_song_row(row: list[_Cell], col_map: dict[str, int]) -> SongVersion | None:
    """Parse a song data row into a SongVersion."""
    name_idx = col_map.get("name", 1)
    raw_name = _get_cell_text(row, name_idx)

    if not raw_name:
        return None

    # Extract badge emoji
    badge, after_badge = extract_badge(raw_name)

    # Parse credits and alt titles from the multi-line name
    title, featuring, producers, collaboration, refs, alt_titles = (
        parse_song_credits(after_badge)
    )

    # Extract version tag from the clean title
    version_tag, _base = extract_version_tag(title)

    # Build the version object
    notes_idx = col_map.get("notes", 2)
    notes_cell = _get_cell(row, notes_idx)
    notes_text = notes_cell.text.strip() if notes_cell.text else None

    # Extract structured metadata from notes
    og_filename = extract_og_filename(notes_text) if notes_text else None
    samples = extract_samples(notes_text) if notes_text else []

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
        name=title,
        version_tag=version_tag,
        badge=badge,
        featuring=featuring,
        producers=producers,
        collaboration=collaboration,
        refs=refs,
        alt_titles=alt_titles,
        notes=notes_text,
        og_filename=og_filename,
        samples=samples,
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
    grouped together. New songs are added to the last (current) section.
    """
    if not era.sections:
        era.sections.append(Section())

    _, base_name = extract_version_tag(version.name)
    # Also strip any sub-info in parens for grouping
    # But keep the base_name as-is for matching — only strip version tags
    base_key = base_name.strip()

    # Search across all sections for grouping (a song may span sections)
    for section in era.sections:
        for song in section.songs:
            if song.base_name == base_key:
                song.versions.append(version)
                return

    # Create new song in the last (current) section
    song = Song(base_name=base_key, versions=[version])
    era.sections[-1].songs.append(song)


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
