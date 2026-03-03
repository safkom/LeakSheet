"""LeakSheet — Data models for music tracker parsing."""

from __future__ import annotations

import re
from enum import Enum

import pydantic
from pydantic import BaseModel, Field

_PYDANTIC_V2 = int(pydantic.VERSION.split(".")[0]) >= 2


class Badge(str, Enum):
    """Song badge / emoji classification."""
    BEST = "best"          # ⭐ ⭐️
    SPECIAL = "special"    # ✨
    WORST = "worst"        # 🗑️
    GRAIL = "grail"        # 🏆
    WANTED = "wanted"      # 🏅 🥇
    AI = "ai"              # 🤖


# Mapping from emoji characters → Badge enum
EMOJI_TO_BADGE: dict[str, Badge] = {
    "⭐": Badge.BEST,
    "⭐️": Badge.BEST,
    "\u2b50": Badge.BEST,       # ⭐ (star)
    "\u2b50\ufe0f": Badge.BEST, # ⭐️ (star + variation selector)
    "💎": Badge.BEST,             # 💎 (gem stone)
    "✨": Badge.SPECIAL,
    "🗑️": Badge.WORST,
    "🗑": Badge.WORST,
    "🏆": Badge.GRAIL,
    "🏅": Badge.WANTED,
    "🥇": Badge.WANTED,
    "\U0001f949": Badge.WANTED,  # 🥉 Bronze medal — "Wanted" (Lil Uzi Vert)
    "🤖": Badge.AI,
}

# Regex to detect and strip leading badge emojis from song names
# Non-badge decorative emojis that precede the actual badge emoji.
# 💿 = disc indicator (e.g. "💿🥉 WOD Tape") — strip before badge detection.
_DECORATIVE_EMOJI = r"[💿🎵🎶🔥]*"

BADGE_EMOJI_PATTERN = re.compile(
    rf"^[\s]*{_DECORATIVE_EMOJI}[\s]*(⭐️|⭐|💎|✨|🗑️|🗑|🏆|🏅|🥇|🥉|🤖)[\s]*"
)

# Regex to extract version tags like [V1], [V2], [Alt.], [Radio Mix], [MASTER], etc.
# Handles:
#   V1, V2, v3                       — numbered versions
#   V1-V3, V2-V25                    — version ranges with known endpoints
#   V1-V?, V2-V?                     — version ranges with unknown upper bound
#   V?                               — unknown version number
#   Alt, Alt.                        — alternate versions
#   Radio Mix, Unfinished            — descriptor versions
#   MASTER, CD VERSION               — recording format versions (Carti tracker)
#   Album, Clean                     — release variant versions
#   Song 1, Song 2                   — ordered song variants (Carti tracker)
VERSION_TAG_PATTERN = re.compile(
    r"\[("
    r"[Vv]\d+(?:-[Vv]?\d+|-[Vv]?\?)?"  # V1, V1-V3, V2-V25, V1-V?, V2-V?
    r"|[Vv]\?"                           # V?
    r"|Alt\.?"                           # Alt, Alt.
    r"|Radio Mix"
    r"|Unfinished"
    r"|MASTER"
    r"|CD VERSION"
    r"|Album"
    r"|Clean"
    r"|Song \d+"                         # Song 1, Song 2
    r")\]",
    re.IGNORECASE,
)


class SongVersion(BaseModel):
    """A specific version of a song with its metadata."""
    name: str = Field(..., description="Song title (first line only, no credits)")
    version_tag: str | None = Field(None, description="Version identifier, e.g. 'V1', 'V2', 'Alt.'")
    badge: Badge | None = Field(None, description="Emoji badge classification")
    featuring: str | None = Field(None, description="Featured artists, e.g. 'Rhymefest & Kanye West'")
    producers: str | None = Field(None, description="Producers, e.g. 'Kanye West & Andy C.'")
    collaboration: str | None = Field(None, description="Collaboration artist, e.g. 'Go Getters'")
    refs: str | None = Field(None, description="Reference track by, e.g. 'Keith Lawson'")
    alt_titles: list[str] = Field(default_factory=list, description="Alternative song titles")
    notes: str | None = Field(None, description="Description/history text")
    og_filename: str | None = Field(None, description="Original filename from metadata, e.g. 'Bitch Im In The CLub NEW'")
    samples: list[str] = Field(default_factory=list, description="Sampled songs/works, e.g. ['Got Money by Lil Wayne']")
    track_length: str | None = Field(None, description="Duration, e.g. '3:14'")
    file_date: str | None = Field(None, description="Date the file was created")
    leak_date: str | None = Field(None, description="Date the version leaked")
    available_length: str | None = Field(None, description="Full/Partial/Snippet/etc.")
    quality: str | None = Field(None, description="CD Quality/High Quality/etc.")
    links: list[str] = Field(default_factory=list, description="Download/reference URLs")
    # Carti-specific fields
    date_of_recording: str | None = Field(None, description="Date of recording (Carti tracker)")
    type: str | None = Field(None, description="Song type (Carti tracker)")


class Song(BaseModel):
    """A logical song that may have multiple versions."""
    base_name: str = Field(..., description="Song name without version tags or badges")
    versions: list[SongVersion] = Field(default_factory=list)

    @property
    def badge(self) -> Badge | None:
        """Return the badge from any version (badges are per-song semantically)."""
        for v in self.versions:
            if v.badge is not None:
                return v.badge
        return None

    @property
    def primary(self) -> SongVersion | None:
        """Return the first/primary version for convenience."""
        return self.versions[0] if self.versions else None

    def dict(self, **kwargs):
        d = super().model_dump(**kwargs) if _PYDANTIC_V2 else super().dict(**kwargs)
        d["badge"] = self.badge.value if self.badge else None
        # Surface primary version metadata at Song level for convenience
        p = self.primary
        if p:
            d["available_length"] = p.available_length
            d["quality"] = p.quality
            d["track_length"] = p.track_length
            d["leak_date"] = p.leak_date
            d["file_date"] = p.file_date
        return d

    def model_dump(self, **kwargs):
        return self.dict(**kwargs)


class EraStats(BaseModel):
    """Parsed statistics from an era header's metadata cell.

    Each tracker era has a stats block like:
        1 OG File(s)
        45 Full
        1 Tagged
        3 Partial
        4 Snippet(s)
        0 Stem Bounce(s)
        70 Unavailable
    """
    og_files: int = Field(0, description="Number of OG files")
    full: int = Field(0, description="Number of full versions")
    tagged: int = Field(0, description="Number of tagged versions")
    partial: int = Field(0, description="Number of partial versions")
    snippets: int = Field(0, description="Number of snippets")
    stem_bounces: int = Field(0, description="Number of stem bounces")
    unavailable: int = Field(0, description="Number of unavailable songs")

    @property
    def total(self) -> int:
        """Total song count from stats (all categories summed)."""
        return (
            self.og_files + self.full + self.tagged + self.partial
            + self.snippets + self.stem_bounces + self.unavailable
        )

    def dict(self, **kwargs):
        d = super().model_dump(**kwargs) if _PYDANTIC_V2 else super().dict(**kwargs)
        d["total"] = self.total
        return d

    def model_dump(self, **kwargs):
        return self.dict(**kwargs)


class TrackerStats(BaseModel):
    """Global tracker statistics found at the bottom of each tracker sheet.

    Contains aggregated totals across all eras.
    """
    # Links
    total_links: int = Field(0)
    missing_links: int = Field(0)
    sources_needed: int = Field(0)
    not_available_links: int = Field(0)

    # Quality
    lossless: int = Field(0)
    cd_quality: int = Field(0)
    high_quality: int = Field(0)
    low_quality: int = Field(0)
    recordings: int = Field(0)
    not_available_quality: int = Field(0)

    # Availability
    total_full: int = Field(0)
    og_files: int = Field(0)
    stem_bounces: int = Field(0)
    full: int = Field(0)
    tagged: int = Field(0)
    partial: int = Field(0)
    snippets: int = Field(0)
    unavailable: int = Field(0)

    # Highlighted / badges
    best_of: int = Field(0)
    special: int = Field(0)
    grails: int = Field(0)
    wanted: int = Field(0)
    worst_of: int = Field(0)


class Section(BaseModel):
    """A named sub-section within an era (e.g. 'Early Sessions', 'July 2020')."""
    name: str = Field("", description="Section name, empty for default section")
    songs: list[Song] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    """A single historical event in an era's timeline."""
    date: str = Field(..., description="Date string, e.g. '06/08/1977', '2016', 'Late 2004'")
    event: str = Field(..., description="Event description")


class Era(BaseModel):
    """An album era / creative period containing songs."""
    name: str = Field(..., description="Era/album name (main title only)")
    alt_names: list[str] = Field(default_factory=list, description="Alternative/working titles for this era")
    description: str | None = Field(None, description="Historical context / notes paragraph")
    timeline: list[TimelineEvent] = Field(default_factory=list, description="Historical timeline events")
    stats_raw: str | None = Field(None, description="Raw stats string, e.g. '3 OG File(s)...'")
    stats: EraStats | None = Field(None, description="Parsed era statistics")
    art_url: str | None = Field(None, description="Cover art image URL for this era")
    highlighted_producers: list[str] = Field(default_factory=list, description="Notable producers for this era")
    sections: list[Section] = Field(default_factory=list)

    @property
    def songs(self) -> list[Song]:
        """Flat list of all songs across all sections."""
        return [s for sec in self.sections for s in sec.songs]

    @property
    def song_count(self) -> int:
        return sum(len(sec.songs) for sec in self.sections)

    @property
    def version_count(self) -> int:
        return sum(len(s.versions) for sec in self.sections for s in sec.songs)

    def dict(self, **kwargs):
        d = super().model_dump(**kwargs) if _PYDANTIC_V2 else super().dict(**kwargs)
        d["sections"] = [
            {"name": sec.name, "songs": [s.dict(**kwargs) for s in sec.songs]}
            for sec in self.sections
        ]
        d["songs"] = [s.dict(**kwargs) for s in self.songs]
        d["song_count"] = self.song_count
        d["version_count"] = self.version_count
        return d

    def model_dump(self, **kwargs):
        return self.dict(**kwargs)


class ParseMetadata(BaseModel):
    """Metadata about the parsing process for debugging and diagnostics."""
    total_rows: int = Field(0, description="Total non-header rows processed")
    song_rows: int = Field(0, description="Rows successfully parsed as songs")
    skipped_rows: int = Field(0, description="Rows that matched no era and were skipped")
    unmatched_rows: list[str] = Field(default_factory=list, description="First 50 unmatched row summaries")
    footer_rows: int = Field(0, description="Rows detected as footer content")
    fuzzy_matched_rows: int = Field(0, description="Rows matched via fuzzy era matching")


class Artist(BaseModel):
    """Top-level artist with all parsed tracker data."""
    name: str = Field(..., description="Artist name")
    slug: str = Field(..., description="URL-safe identifier")
    source_url: str | None = Field(None, description="Original Google Sheets URL")
    eras: list[Era] = Field(default_factory=list)
    tracker_stats: TrackerStats | None = Field(None, description="Global tracker statistics")
    parse_metadata: ParseMetadata | None = Field(None, description="Parsing diagnostics")

    @property
    def total_songs(self) -> int:
        return sum(e.song_count for e in self.eras)

    @property
    def total_versions(self) -> int:
        return sum(e.version_count for e in self.eras)

    def dict(self, **kwargs):
        d = super().model_dump(**kwargs) if _PYDANTIC_V2 else super().dict(**kwargs)
        d["eras"] = [era.dict(**kwargs) for era in self.eras]
        d["total_songs"] = self.total_songs
        d["total_versions"] = self.total_versions
        return d

    def model_dump(self, **kwargs):
        return self.dict(**kwargs)


def extract_badge(name: str) -> tuple[Badge | None, str]:
    """Extract leading badge emoji from a song name.

    Returns (badge, cleaned_name) where cleaned_name has the emoji stripped.
    """
    match = BADGE_EMOJI_PATTERN.match(name)
    if match:
        emoji = match.group(1)
        badge = EMOJI_TO_BADGE.get(emoji)
        cleaned = name[match.end():].strip()
        return badge, cleaned
    return None, name.strip()


def extract_version_tag(name: str) -> tuple[str | None, str]:
    """Extract version tag from a song name.

    Returns (version_tag, base_name) where base_name has the tag stripped.
    """
    match = VERSION_TAG_PATTERN.search(name)
    if match:
        tag = match.group(1)
        # Remove the [Vx] portion to get the base name
        before = name[:match.start()].strip()
        after = name[match.end():].strip()
        base = (before + " " + after).strip() if before and after else (before or after)
        return tag, base
    return None, name.strip()


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


# ---------------------------------------------------------------------------
# Stats parsing
# ---------------------------------------------------------------------------

# Regex to extract "N Label" pairs from stats text.
# Handles both concatenated ("1 OG File(s)45 Full") and newline-separated formats.
# Also handles emoji-prefixed labels ("🔗 616 Total Links").
_STAT_LINE_PATTERN = re.compile(
    r"(\d+)\s+([A-Za-z][A-Za-z /()]+?)(?=\d|\Z)",
)


def _extract_stat_pairs(raw: str) -> dict[str, int]:
    """Parse stats text into {lowercase_label: count} dict.

    Handles both formats:
      "1 OG File(s)\\n45 Full\\n1 Tagged..."
      "🔗 616 Total Links\\n❌ 0 Missing Links..."
    """
    # Strip all emoji characters first
    cleaned = re.sub(
        r"[\U0001f300-\U0001f9ff\u2600-\u27bf\u2b50\ufe0f\u200d]+",
        "",
        raw,
    )
    # Replace newlines with a separator that won't interfere
    cleaned = cleaned.replace("\n", " ")
    # Collapse multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    result: dict[str, int] = {}
    for m in _STAT_LINE_PATTERN.finditer(cleaned):
        count = int(m.group(1))
        label = m.group(2).strip().lower()
        # Normalize: strip "(s)" suffix (e.g. "Snippet(s)" → "snippet")
        if label.endswith("(s)"):
            label = label[:-3]
        elif label.endswith("("):
            label = label[:-1]
        result[label] = count
    return result


def parse_era_stats(raw: str) -> EraStats:
    """Parse a raw era stats string into an EraStats model."""
    pairs = _extract_stat_pairs(raw)

    return EraStats(
        og_files=pairs.get("og file", pairs.get("og files", 0)),
        full=_match_stat(pairs, ["total full", "full"]),
        tagged=pairs.get("tagged", 0),
        partial=_match_stat(pairs, ["partial", "partial / cut"]),
        snippets=pairs.get("snippet", pairs.get("snippets", 0)),
        stem_bounces=pairs.get("stem bounce", pairs.get("stem bounces", 0)),
        unavailable=pairs.get("unavailable", 0),
    )


def _match_stat(pairs: dict[str, int], keys: list[str]) -> int:
    """Return the first matching stat value from a list of priority keys."""
    for key in keys:
        if key in pairs:
            return pairs[key]
    return 0


def parse_tracker_stats(
    links_text: str,
    quality_text: str,
    availability_text: str,
    highlights_text: str,
) -> TrackerStats:
    """Parse the global stats row into a TrackerStats model.

    Each argument is the raw text from one cell of the global stats row.
    """
    lp = _extract_stat_pairs(links_text) if links_text else {}
    qp = _extract_stat_pairs(quality_text) if quality_text else {}
    ap = _extract_stat_pairs(availability_text) if availability_text else {}
    hp = _extract_stat_pairs(highlights_text) if highlights_text else {}

    return TrackerStats(
        # Links
        total_links=lp.get("total links", lp.get("total link", 0)),
        missing_links=lp.get("missing links", lp.get("missing link", 0)),
        sources_needed=lp.get("sources needed", 0),
        not_available_links=_match_stat(lp, ["not avaliable", "not available"]),

        # Quality
        lossless=qp.get("lossless", 0),
        cd_quality=qp.get("cd quality", 0),
        high_quality=qp.get("high quality", 0),
        low_quality=qp.get("low quality", 0),
        recordings=qp.get("recordings", qp.get("recording", 0)),
        not_available_quality=_match_stat(qp, ["not available", "not avaliable"]),

        # Availability
        total_full=ap.get("total full", 0),
        og_files=ap.get("og files", ap.get("og file", 0)),
        stem_bounces=ap.get("stem bounces", ap.get("stem bounce", 0)),
        full=ap.get("full", 0),
        tagged=ap.get("tagged", 0),
        partial=ap.get("partial", 0),
        snippets=ap.get("snippets", ap.get("snippet", 0)),
        unavailable=_match_stat(ap, ["unavailable"]),

        # Highlighted
        best_of=hp.get("best of", 0),
        special=hp.get("special", 0),
        grails=hp.get("grails", hp.get("grail", 0)),
        wanted=hp.get("wanted", 0),
        worst_of=hp.get("worst of", 0),
    )


# ---------------------------------------------------------------------------
# Song credit parsing
# ---------------------------------------------------------------------------

# Patterns for extracting credit info from song name sub-lines
_FEAT_PATTERN = re.compile(r"\((?:feat\.?|featuring|ft\.?)\s+(.+?)\)", re.IGNORECASE)
_PROD_PATTERN = re.compile(r"\(prod\.?\s+(.+?)\)", re.IGNORECASE)
_WITH_PATTERN = re.compile(r"\(with\s+(.+?)\)", re.IGNORECASE)
_REF_PATTERN = re.compile(r"\(ref\.?\s+(.+?)\)", re.IGNORECASE)


def parse_song_credits(
    raw_name: str,
) -> tuple[str, str | None, str | None, str | None, str | None, list[str]]:
    """Parse a raw multi-line song name into title + structured credits.

    Raw names look like:
        10 in a Benz
        (with Go Getters) (feat. Rhymefest) (prod. Kanye West & Andy C.)
        (On 10 in a Benz)

    Returns (title, featuring, producers, collaboration, refs, alt_titles).
    """
    text = raw_name

    # Extract all credit patterns from full text
    feat_matches = _FEAT_PATTERN.findall(text)
    prod_matches = _PROD_PATTERN.findall(text)
    with_matches = _WITH_PATTERN.findall(text)
    ref_matches = _REF_PATTERN.findall(text)

    # Remove credit patterns to get clean text
    cleaned = _FEAT_PATTERN.sub("", text)
    cleaned = _PROD_PATTERN.sub("", cleaned)
    cleaned = _WITH_PATTERN.sub("", cleaned)
    cleaned = _REF_PATTERN.sub("", cleaned)

    # Split by newline: first line = title, rest = alt titles
    lines = [ln.strip() for ln in cleaned.split("\n")]
    title = lines[0].strip()

    # Remaining non-empty lines → alt titles
    alt_titles: list[str] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        # Strip wrapping parens: "(All I Have)" → "All I Have"
        if line.startswith("(") and line.endswith(")"):
            alt_titles.append(line[1:-1].strip())
        else:
            alt_titles.append(line)

    featuring = ", ".join(feat_matches) if feat_matches else None
    producers = ", ".join(prod_matches) if prod_matches else None
    collaboration = ", ".join(with_matches) if with_matches else None
    refs = ", ".join(ref_matches) if ref_matches else None

    return title, featuring, producers, collaboration, refs, alt_titles


# ---------------------------------------------------------------------------
# Timeline parsing
# ---------------------------------------------------------------------------

# Matches a line starting with (date) followed by optional (event) or event text
_TIMELINE_LINE_PATTERN = re.compile(r"^\(([^)]+)\)\s*(.*)", re.MULTILINE)


def parse_timeline(text: str) -> list[TimelineEvent]:
    """Parse timeline text into a list of TimelineEvent objects.

    Handles two formats:
      - Ye/Kendrick: (06/08/1977) (Ye is born in Atlanta)
      - Keem/Carti:  (2016) Baby Keem releases "Come Thru" to soundcloud.
    """
    events: list[TimelineEvent] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _TIMELINE_LINE_PATTERN.match(line)
        if m:
            date = m.group(1).strip()
            rest = m.group(2).strip()
            # Strip wrapping parens from event if present
            if rest.startswith("(") and rest.endswith(")"):
                event = rest[1:-1].strip()
            else:
                event = rest
            if date and event:
                events.append(TimelineEvent(date=date, event=event))
    return events


# ---------------------------------------------------------------------------
# Notes metadata extraction
# ---------------------------------------------------------------------------

# OG Filename patterns:
#   "OG Filename (Metadata): Bitch Im In The CLub NEW"
#   "OG Filename: Broke My Heart 1"
_OG_FILENAME_PATTERN = re.compile(
    r"OG Filename(?:\s*\(Metadata\))?:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# Samples patterns:
#   'Samples "Got Money" by Lil Wayne'
#   "Samples Rufus & Chaka Khan's 'Ain't Nobody'"
#   'Samples "Ain\'t Nobody" by Rufus & Chaka Khan'
_SAMPLES_PATTERN = re.compile(
    r"""Samples\s+[""\u201c](.+?)[""\u201d](?:\s+by\s+(.+?))?(?:\.|,|\n|$)"""
    r"""|Samples\s+(.+?)(?:'s\s+)?["'\u2018\u2019](.+?)["'\u2018\u2019]""",
    re.IGNORECASE,
)


def extract_og_filename(notes: str) -> str | None:
    """Extract OG Filename from notes text.

    Returns the filename string or None.
    """
    m = _OG_FILENAME_PATTERN.search(notes)
    if m:
        return m.group(1).strip()
    return None


def extract_samples(notes: str) -> list[str]:
    """Extract sampled works from notes text.

    Returns list of sample descriptions, e.g. ['"Got Money" by Lil Wayne'].
    """
    results: list[str] = []
    for m in _SAMPLES_PATTERN.finditer(notes):
        if m.group(1):
            # Pattern 1: Samples "Song" by Artist
            song = m.group(1).strip()
            artist = m.group(2).strip() if m.group(2) else None
            if artist:
                results.append(f'"{song}" by {artist}')
            else:
                results.append(f'"{song}"')
        elif m.group(3):
            # Pattern 2: Samples Artist's "Song"
            artist = m.group(3).strip()
            song = m.group(4).strip() if m.group(4) else ""
            if song:
                results.append(f'"{song}" by {artist}')
            else:
                results.append(artist)
    return results


def parse_highlighted_producers(text: str) -> list[str]:
    """Parse 'Highlighted Producers' cell text into a list of producer names.

    Input format: "Highlighted Producers:\\n- Kanye West\\n- No I.D.\\n- ???"
    Returns: ["Kanye West", "No I.D."] (filters out "???")
    """
    producers: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            name = line[2:].strip()
            if name and name != "???" and name != "N/A":
                producers.append(name)
    return producers
