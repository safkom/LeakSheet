"""LeakSheet — HTML parser for Google Sheets tracker exports.

Parses the htmlview export of a Google Spreadsheet music tracker into
structured Artist/Era/Song/SongVersion objects.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

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
# Parser tuning constants
# ---------------------------------------------------------------------------

# Maximum number of rows to scan when looking for the header row.
# Some trackers have instruction/title rows before the actual column headers.
_MAX_HEADER_SCAN_ROWS = 11

# Cap on unmatched rows recorded for diagnostics — prevents unbounded list growth
# on trackers that have many footers, annotations, or oddly structured rows.
_MAX_UNMATCHED_ROWS = 50


# ---------------------------------------------------------------------------
# Stylesheet color extraction
# ---------------------------------------------------------------------------

# Match CSS class rules like ".s263{...; background-color:#4caf50; ...}"
_CSS_CLASS_RULE_RE = re.compile(
    r"\.(s\d+)\s*\{([^}]+)\}",
    re.DOTALL,
)
_BG_COLOR_RE = re.compile(
    r"background-color\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\)|rgba\([^)]+\))",
    re.IGNORECASE,
)
# Colors considered "default" / neutral — skip these (won't provide UX value)
_NEUTRAL_HEX = frozenset({
    "#ffffff", "#fff", "#000000", "#000",
    "#fafafa", "#f8f9fa", "#f3f3f3", "#eeeeee",
    "#cccccc", "#1e1e1e", "#1a1a1a", "#1f1f1f",
    "#2a2a2a", "#161616", "#0f0f0f", "#0d0d0d",
})


def _extract_class_colors(html: str) -> dict[str, str]:
    """Parse the <style> section of a Google Sheets HTML export and return
    a mapping of {css_class_name: hex_background_color} for non-neutral cells.

    Only classes with an explicit, non-neutral background-color are included.
    """
    result: dict[str, str] = {}
    # Find the first <style> block
    style_match = re.search(r"<style[^>]*>(.*?)</style>", html, re.DOTALL | re.IGNORECASE)
    if not style_match:
        return result

    style_text = style_match.group(1)
    for m in _CSS_CLASS_RULE_RE.finditer(style_text):
        cls = m.group(1)  # e.g. "s263"
        decl = m.group(2)
        bg_match = _BG_COLOR_RE.search(decl)
        if not bg_match:
            continue
        color = bg_match.group(1).strip().lower()
        # Convert rgb(...) to hex
        if color.startswith("rgb"):
            try:
                nums = re.findall(r"\d+", color)
                if len(nums) >= 3:
                    r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
                    color = f"#{r:02x}{g:02x}{b:02x}"
            except ValueError:
                continue
        if color in _NEUTRAL_HEX:
            continue
        result[cls] = color

    return result


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
    """A single table cell with text content, extracted links, images, CSS class, and bg color."""
    __slots__ = ("text", "links", "images", "css_class", "bg_color")

    def __init__(
        self,
        text: str = "",
        links: list[str] | None = None,
        images: list[str] | None = None,
        css_class: str = "",
        bg_color: str | None = None,
    ) -> None:
        self.text = text
        self.links = links or []
        self.images = images or []
        self.css_class = css_class
        self.bg_color = bg_color
        self.css_class = css_class

    def __repr__(self) -> str:
        parts = [f"Cell({self.text!r}"]
        if self.links:
            parts.append(f", links={len(self.links)}")
        if self.images:
            parts.append(f", imgs={len(self.images)}")
        return "".join(parts) + ")"


def extract_table(html_content: str, color_map: dict[str, str] | None = None) -> list[list[_Cell]]:
    """Parse HTML and return all table rows as lists of _Cell.

    If *color_map* is provided (from `_extract_class_colors`), each cell's
    `bg_color` is resolved from its CSS class at construction time.
    """
    parser = _TableExtractor()
    parser.feed(html_content)
    if not color_map:
        return parser.rows
    # Resolve bg_color for every cell whose class is in color_map
    for row in parser.rows:
        for cell in row:
            if cell.css_class and cell.css_class in color_map:
                cell.bg_color = color_map[cell.css_class]
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
        key = re.sub(r'\s+', ' ', key)  # normalize internal whitespace (e.g. 'file \ndate' → 'file date')

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
# Also matches variant formats found across 400+ trackers:
#   - "3 of Leaks\n0 of Snippets" (Billie Eilish)
#   - "0 Streaming | 1 Off-Streaming" (Joji)
#   - "27 tracks" (Gucci Mane, Chief Keef)
#   - "0 Released | 1 Deleted | 5 Lost" (XXXTENTACION)
#   - "5 Leaks\n2 Snippets" (common template variant)
ERA_STATS_PATTERN = re.compile(
    r"\d+\s+"
    r"("
    r"OG File|Total Full|Full|Tagged|Partial|Snippet|Stem|Unavailable"
    r"|Edited"                                                          # Michael Jackson
    r"|of Leaks|of Snippets|of Partials|of Recordings|of Unavailable|of Full"
    r"|Leaks?|Snippets?|Partials?"
    r"|Streaming|Off-Streaming|Off Streaming|On Streaming|On-Streaming"
    r"|tracks?|songs?"
    r"|Released|Deleted|Lost|Privated"
    r")",
    re.IGNORECASE,
)

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
    "og files for released songs",
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
    """
    if not row:
        return False
    text = row[0].text
    if not ERA_STATS_PATTERN.search(text):
        return False
    # Real era headers have at least one cell (or first line of cell 0) that
    # contains a non-numeric, non-stats era name.  Global stats rows have
    # only stat-like content (numbers + keywords) in every cell.
    _NUMERIC_STAT_RE = re.compile(r"^\d+\s")
    for c in row:
        first_line = c.text.split("\n")[0].strip()
        if not first_line:
            continue
        # If the first line doesn't start with a digit, it's likely an era name
        if not _NUMERIC_STAT_RE.match(first_line):
            return True
        # Check for images (era art) — a strong signal this is an era header
        if c.images:
            return True
    # Every non-empty cell starts with "N something" — pure stats row
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
        "current editor", "current editors", "editor comments",
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
    # The text cell must be short and single-line
    text_cell = max(non_empty, key=lambda x: len(x[1].text.strip()))
    label = text_cell[1].text.strip()
    if len(label) > 60 or "\n" in label:
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
                result.remove(empty_era)
                break

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


def _normalize_unicode(text: str) -> str:
    """Normalize Unicode text by replacing diacritics with their base characters.

    Handles cases like "geëky" → "geeky", "ROSALÍA" → "ROSALIA".
    """
    # NFKD decomposition splits characters like ë into e + combining diaeresis
    decomposed = unicodedata.normalize("NFKD", text)
    # Remove combining characters (diacritics)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


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
    - "(Mollyworld, Balaclava Era)" → "mollyworld, balaclava era"
    - "Super geëky" → "super geeky"  (diacritics normalized)
    """
    key = full_era_name
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

    if best_score >= 0.5 and best_match is not None:
        return best_match

    # Acronym matching: if key matches the acronym of a known era.
    # e.g. "sftsaftm" → "Shoot For The Stars Aim For The Moon"
    key_clean = key.replace(" ", "")
    if len(key_clean) >= 3:
        for era_key, era in era_by_key.items():
            era_words = era_key.split()
            if len(era_words) >= 3:
                acro = "".join(w[0] for w in era_words if w)
                if acro and key_clean == acro:
                    return era

    return None


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


def _register_era_keys(
    era: Era,
    era_name: str,
    era_by_key: dict[str, Era],
) -> None:
    """Register all matching keys for an era (primary, full, alt-names, slash parts).

    Uses setdefault so earlier (more authoritative) registrations win.
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
    # Slash-separated: "38 Baby / Ay Ay" → register both parts
    if " / " in era_name:
        for part in era_name.split(" / "):
            part_key = _era_match_key(part)
            if part_key:
                era_by_key.setdefault(part_key, era)


# ---------------------------------------------------------------------------
# High-level parser
# ---------------------------------------------------------------------------

def _has_song_data(v: SongVersion) -> bool:
    """Return True if the version has at least one song-like metadata field."""
    return bool(
        v.links or v.quality or v.track_length
        or v.available_length or v.leak_date or v.file_date
    )


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

    # Check name cell for images.
    # If the cell also has usable text, the image is album art.
    # If the cell has NO text (image-based era name like Carti's
    # Narcissist logo), the image is the era name — not art.
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


def parse_sheet(html_content: str, artist_name: str) -> Artist:
    """Parse a Google Sheets HTML export into an Artist model.

    This is the main entry point for parsing a single tracker.
    """
    # Extract cell background colors from the stylesheet (non-neutral only)
    color_map = _extract_class_colors(html_content)
    rows = extract_table(html_content, color_map)
    if not rows:
        return Artist(name=artist_name, slug=slugify(artist_name), eras=[])

    # Step 1: detect column layout from header row.
    header_row_idx, col_map = _detect_header_row(rows)

    # Step 2: walk rows, classify and extract
    eras: list[Era] = []
    current_era: Era | None = None
    # Map from lowercased era matching key → Era object.
    # Keys are lowercase, parenthetical-stripped, version-tag-stripped.
    era_by_key: dict[str, Era] = {}
    # Eras whose name cell had an image but no usable text — backfill from
    # the first song row's era column.
    _needs_name_backfill: set[int] = set()  # id(era) values
    in_footer = False

    # Parse metadata tracking
    total_rows = len(rows) - 1 - header_row_idx  # exclude header and pre-header rows
    song_rows = 0
    skipped_rows = 0
    unmatched_rows: list[str] = []
    footer_rows = 0
    fuzzy_matched_rows = 0

    for row_idx, row in enumerate(rows):
        # Skip header row and any rows before it (title/instruction rows)
        if row_idx <= header_row_idx:
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
            current_era, needs_backfill = _parse_era_header_row(row, col_map)
            eras.append(current_era)
            _register_era_keys(current_era, current_era.name, era_by_key)
            if needs_backfill:
                _needs_name_backfill.add(id(current_era))
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

        # If current era needs name backfill (image-only header), assign
        # this song row to it *before* the normal lookup — otherwise fuzzy
        # matching can steal it for a similarly-named era (e.g. WLR [V3]
        # swallowing WLR [V4] songs because version tags are stripped).
        if (
            row_era
            and current_era is not None
            and id(current_era) in _needs_name_backfill
        ):
            current_era.name = row_era
            _register_era_keys(current_era, row_era, era_by_key)
            _needs_name_backfill.discard(id(current_era))
            version = _parse_song_row(row, col_map)
            if version:
                _add_version_to_era(current_era, version)
                song_rows += 1
            continue

        if row_era:
            # Case-insensitive exact lookup with Unicode normalization
            row_era_norm = _normalize_unicode(row_era).lower()
            matched_era = era_by_key.get(row_era_norm)

            # Try stripped key (version tags removed) if exact fails
            if matched_era is None:
                row_era_stripped = _era_match_key(row_era)
                if row_era_stripped != row_era_norm:
                    matched_era = era_by_key.get(row_era_stripped)

            # Fuzzy match if exact lookup fails
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
                        _add_version_to_era(current_era, version)
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
                        _add_version_to_era(current_era, version)
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
                        # If the row has actual song metadata (links, quality, etc.),
                        # prefer assigning to current_era over creating a new one.
                        # This handles trackers where song rows use different era
                        # abbreviations than the header (e.g. Pop Smoke, Jay-Z).
                        if _has_song_data(version):
                            _add_version_to_era(current_era, version)
                            song_rows += 1
                            # Register this era name variant for future rows
                            era_by_key.setdefault(_era_match_key(row_era), current_era)
                        else:
                            new_era = Era(name=row_era, sections=[Section()])
                            eras.append(new_era)
                            _register_era_keys(new_era, row_era, era_by_key)
                            current_era = new_era
                    elif version:
                        # Not a plausible era name but has song data —
                        # assign to current era as fallback
                        _add_version_to_era(current_era, version)
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
                            # Scan for cover art
                            _era_art_url_candidate = None
                            for cell in row:
                                if cell.images and not _era_art_url_candidate:
                                    _era_art_url_candidate = cell.images[0]
                                    break
                            new_era = Era(name=row_era, timeline=timeline, art_url=_era_art_url_candidate, sections=[Section()])
                            eras.append(new_era)
                            _register_era_keys(new_era, row_era, era_by_key)
                            current_era = new_era
                    continue
            else:
                # No current era at all — auto-create from this row.
                # Handles trackers with no era headers (Young Thug, etc.)
                if not _looks_like_era_name(row_era):
                    # Skip non-era rows (announcements, footers, etc.)
                    skipped_rows += 1
                    if len(unmatched_rows) < _MAX_UNMATCHED_ROWS:
                        row_text = " | ".join(c.text.strip() for c in row if c.text.strip())[:200]
                        if row_text:
                            unmatched_rows.append(f"Row {row_idx}: {row_text}")
                    continue

                version = _parse_song_row(row, col_map)
                if version:
                    new_era = Era(name=row_era, sections=[Section()])
                    eras.append(new_era)
                    _register_era_keys(new_era, row_era, era_by_key)
                    current_era = new_era
                    _add_version_to_era(current_era, version)
                    song_rows += 1
                else:
                    # No song data — stats-less era header (Kid Cudi style)
                    notes_idx = col_map.get("notes", 2)
                    name_idx = col_map.get("name", 1)
                    timeline_raw = _get_cell_text(row, notes_idx) or _get_cell_text(row, name_idx)
                    timeline = parse_timeline(timeline_raw) if timeline_raw else []
                    # Scan for cover art
                    _era_art_url_candidate = None
                    for cell in row:
                        if cell.images and not _era_art_url_candidate:
                            _era_art_url_candidate = cell.images[0]
                            break
                    new_era = Era(name=row_era, timeline=timeline, art_url=_era_art_url_candidate, sections=[Section()])
                    eras.append(new_era)
                    _register_era_keys(new_era, row_era, era_by_key)
                    current_era = new_era
                continue

        # Sub-era section header OR name-column era header:
        # era_col is empty but name_col has text, with very few filled cells.
        # In Yung Lean, "Before Unknown Death" appears in the name column
        # as an era header. In other trackers, this is a section label.
        # Travis Scott tracker: era header rows have the era name on line 1
        # and a year-range on line 2 (via a <br> tag), e.g.:
        #   "The Graduates\n(2007 - 2009)"
        # Sub-section rows ("Other Media", "Production", etc.) only have a
        # single-line label with no embedded newline.
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
                    # Scan cells for cover art (same logic as _is_era_header path)
                    _era_art_url = None
                    _name_cell_ml = _get_cell(row, name_col_idx)
                    if _name_cell_ml.images and name_first_line:
                        _era_art_url = _name_cell_ml.images[0]
                    for col_idx, cell in enumerate(row):
                        if col_idx == name_col_idx:
                            continue
                        if cell.images and not _era_art_url:
                            _era_art_url = cell.images[0]
                            break
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
            dyn_label = _is_dynamic_section_label(row, col_map)
            if dyn_label:
                current_era.sections.append(Section(name=dyn_label))
                continue

        # Positional fallback: era column is empty but current_era exists.
        # Many trackers (Glaive, etc.) leave the era column blank for song rows
        # and only fill it for era headers.  If the row has enough filled cells
        # to look like a song, try to parse it and assign positionally.
        if not row_era and current_era is not None:
            version = _parse_song_row(row, col_map)
            if version and (version.name or _has_song_data(version)):
                _add_version_to_era(current_era, version)
                song_rows += 1
                continue

        # Unmatched row — track it for diagnostics
        skipped_rows += 1
        if len(unmatched_rows) < _MAX_UNMATCHED_ROWS:
            row_text = " | ".join(c.text.strip() for c in row if c.text.strip())[:200]
            if row_text:
                unmatched_rows.append(f"Row {row_idx}: {row_text}")

    # Step 3: detect and parse global stats row
    tracker_stats = _find_global_stats(rows)

    # Step 3b: merge 0-song stub eras (from name-column era headers) into
    # their adjacent songs-bearing eras.  Handles trackers like Travis Scott
    # 2.0 where full era names in header rows differ from abbreviated era
    # names used in song rows (e.g. "Birds In The Trap Sing McKnight" vs "Birds").
    eras = _merge_empty_stub_eras(eras)

    # Step 3c: consolidate group labels within each era's sections
    for era in eras:
        _consolidate_group_labels(era)

    # Step 4: build parse metadata
    metadata = ParseMetadata(
        total_rows=total_rows,
        song_rows=song_rows,
        skipped_rows=skipped_rows,
        unmatched_rows=unmatched_rows,
        footer_rows=footer_rows,
        fuzzy_matched_rows=fuzzy_matched_rows,
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

    # Extract structured metadata from notes
    og_filename = extract_og_filename(notes_text) if notes_text else None
    samples = extract_samples(notes_text) if notes_text else []

    links_idx = col_map.get("links")
    alt_links_idx = col_map.get("alt_links")
    link_cell = _get_cell(row, links_idx) if links_idx is not None else _Cell()
    alt_link_cell = _get_cell(row, alt_links_idx) if alt_links_idx is not None else _Cell()
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
        quality_color=_get_cell(row, col_map.get("quality", -1)).bg_color if col_map.get("quality") is not None else None,
        available_length_color=_get_cell(row, col_map.get("available_length", -1)).bg_color if col_map.get("available_length") is not None else None,
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
# Art tab parsing — high-quality era artwork
# ---------------------------------------------------------------------------

def parse_art_tab(html: str) -> dict[str, str]:
    """Parse an Art tab HTML export → {era_match_key: image_url} mapping.

    Art tabs in tracker spreadsheets contain full-resolution era artwork.
    Each row typically has an era name in one cell and one or more images.

    Multiple images may appear per era (front cover, back cover, promo photo,
    background art, etc.).  We prefer images whose row contains descriptive
    text that mentions "cover" — e.g. "Front Cover", "Album Cover", "Cover Art".
    If no cover-labelled image is found for an era, we fall back to the first
    available image in the row.

    Returns a dict keyed by the normalised era match key (lowercase, stripped).
    """
    rows = extract_table(html)
    if not rows:
        return {}

    # Skip header row if it has no images (it's a label row)
    start = 1 if rows and not any(cell.images for cell in rows[0]) else 0

    # First pass: collect all images per era key, noting which have cover descriptions.
    # era_info: {era_key: {"cover": url, "first": url}}
    era_info: dict[str, dict[str, str | None]] = {}

    for row in rows[start:]:
        if not row:
            continue

        # First image found in the row is the candidate
        img_url = next((cell.images[0] for cell in row if cell.images), None)
        if not img_url:
            continue

        # First non-empty text cell is the era name
        era_name = next((cell.text.strip() for cell in row if cell.text.strip()), "")
        if not era_name:
            continue

        key = _era_match_key(era_name)
        if not key:
            continue

        if key not in era_info:
            era_info[key] = {"cover": None, "first": None}

        # Record the first image seen for this era
        if era_info[key]["first"] is None:
            era_info[key]["first"] = img_url

        # Check if any cell text in this row mentions "cover"
        row_text = " ".join(c.text.strip() for c in row if c.text.strip())
        if era_info[key]["cover"] is None and _COVER_RE.search(row_text):
            era_info[key]["cover"] = img_url

    # Build final map: prefer cover-labelled image, fall back to first image
    result: dict[str, str] = {}
    for key, info in era_info.items():
        chosen = info["cover"] or info["first"]
        if chosen:
            result[key] = chosen

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
    key = _era_match_key(era.name)
    if key and key in art_map:
        era.art_url = art_map[key]
        return
    for alt in era.alt_names:
        alt_key = _era_match_key(alt)
        if alt_key and alt_key in art_map:
            era.art_url = art_map[alt_key]
            return


# ---------------------------------------------------------------------------
# File-level convenience
# ---------------------------------------------------------------------------

def parse_file(path: Path | str, artist_name: str) -> Artist:
    """Parse a tracker HTML file into an Artist model."""
    path = Path(path)
    html_content = path.read_text(encoding="utf-8")
    return parse_sheet(html_content, artist_name)



