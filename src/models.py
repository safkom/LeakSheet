"""LeakSheet — Data models for music tracker parsing."""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

from pydantic import BaseModel, Field


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


class SourceRef(BaseModel):
    """A labeled evidence link from a tracker's Sources column.

    E.g. label='First Mention (Screenshot)', url='https://imgur.com/…' —
    provenance for how a leak/track is known, distinct from listen links.
    """
    label: str = Field("", description="Human label from the source cell line")
    url: str = Field(..., description="Evidence URL")


class SongVersion(BaseModel):
    """A specific version of a song with its metadata."""
    name: str = Field(..., description="Song title (first line only, no credits)")
    version_tag: str | None = Field(None, description="Version identifier, e.g. 'V1', 'V2', 'Alt.'")
    badge: Badge | None = Field(None, description="Emoji badge classification")
    featuring: str | None = Field(None, description="Featured artists, e.g. 'Rhymefest & Kanye West'")
    producers: str | None = Field(None, description="Producers, e.g. 'Kanye West & Andy C.'")
    credited_artists: str | None = Field(
        None,
        description="Performer(s) from a dedicated Artist/Credited Artist column "
        "(collab-style trackers) — the row's performing artist, not a feature",
    )
    collaboration: str | None = Field(None, description="Collaboration artist, e.g. 'Go Getters'")
    refs: str | None = Field(None, description="Reference track by, e.g. 'Keith Lawson'")
    director: str | None = Field(None, description="Director credit on video rows, e.g. 'Dave Meyers'")
    alt_titles: list[str] = Field(default_factory=list, description="Alternative song titles")
    notes: str | None = Field(None, description="Description/history text")
    og_filename: str | None = Field(None, description="First original filename from metadata (legacy single-value field)")
    og_filenames: list[str] = Field(default_factory=list, description="All original filenames from metadata, in order of appearance")
    samples: list[str] = Field(default_factory=list, description="Sampled songs/works, e.g. ['Got Money — Lil Wayne']")
    sources: list[SourceRef] = Field(default_factory=list, description="Labeled evidence links from a Sources column")
    track_length: str | None = Field(None, description="Duration, e.g. '3:14'")
    file_date: str | None = Field(None, description="Date the file was created")
    leak_date: str | None = Field(None, description="Date the version leaked")
    available_length: str | None = Field(None, description="Full/Partial/Snippet/etc.")
    quality: str | None = Field(None, description="CD Quality/High Quality/etc.")
    streaming: bool | None = Field(None, description="Streaming Yes/No (main-tab Streaming column)")
    rating: int | None = Field(None, description="Fan star rating 1-5 (Travis-style ⭐ suffix in the availability cell)")
    links: list[str] = Field(default_factory=list, description="Download/reference URLs")
    # Carti-specific fields
    date_of_recording: str | None = Field(None, description="Date of recording (Carti tracker)")
    type: str | None = Field(None, description="Song type (Carti tracker)")


class Song(BaseModel):
    """A logical song that may have multiple versions."""
    base_name: str = Field(..., description="Song name without version tags or badges")
    song_key: str = Field(
        default="",
        description=(
            "Stable normalized identity key (case/diacritics/punctuation "
            "collapsed) shared by the same song across eras; empty for "
            "unidentified placeholder tracks"
        ),
    )
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
        d = super().model_dump(**kwargs)
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
        d = super().model_dump(**kwargs)
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
    group: str | None = Field(None, description="Parent group label (e.g. 'Die Lit 2', 'Kanye West - Donda')")
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
        # Exclude ``sections`` from the native dump — it's rebuilt below, so
        # letting the native pass serialize the song/version subtree first is
        # pure waste (see Artist.dict for the same optimization).
        kwargs = _with_excluded(kwargs, "sections")
        # stats/stats_raw/highlighted_producers STAY on the wire even though
        # no client reads them (2026-07-24 review): the /sheet warm path
        # serves the parsed-cache file's raw bytes as the response, so cache
        # and wire are the same serialization — excluding them here would
        # also strip them from the cache round-trip, silently blinding the
        # starved-era health check (tests/_health.py) and census has_stats
        # on every cache hit. Clients just ignore them.
        d = super().model_dump(**kwargs)
        d["sections"] = [
            {"name": sec.name, "group": sec.group, "songs": [s.dict() for s in sec.songs]}
            for sec in self.sections
        ]
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
    unmatched_rows_total: int = Field(0, description="Total unmatched rows encountered (uncapped)")
    footer_rows: int = Field(0, description="Rows detected as footer content")
    other_rows: int = Field(
        0,
        description="Structural rows (era headers, section labels, separators) "
        "that are neither songs, skipped, nor footer. Lets clients verify the "
        "row-accounting identity total == song + skipped + footer + other.",
    )
    fuzzy_matched_rows: int = Field(0, description="Rows matched via fuzzy era matching")
    dropped_columns: list[str] = Field(
        default_factory=list,
        description="Non-empty header cells that matched no known column alias",
    )


class MiscEntry(BaseModel):
    """One entry from a secondary tracker tab (Misc / Music Videos).

    These tabs share the main tracker's era-grouped grammar but carry their
    own column sets and are kept fully separate from the era/song tree.
    """
    era_name: str = Field("", description="Era label from the last era header row")
    section: str = Field(
        "",
        description=(
            "Label from the last section separator row, e.g. the 'Grails' / "
            "'Wanted' blocks inside a combined highlight tab"
        ),
    )
    name: str = Field(..., description="Entry title")
    notes: str | None = Field(None, description="Description text")
    entry_type: str | None = Field(None, description="Type column, e.g. 'Released', 'Freestyle', 'Book'")
    date: str | None = Field(None, description="Date / Release Date column")
    length: str | None = Field(None, description="Length / Media Length column")
    available: str | None = Field(None, description="Available column (Misc tab)")
    quality: str | None = Field(None, description="Quality column (Misc tab)")
    streaming: bool | None = Field(None, description="Streaming Yes/No (Music Videos tab)")
    links: list[str] = Field(default_factory=list, description="Entry URLs")
    source_tab: str = Field(
        ...,
        description=(
            "Tab kind the entry came from: 'misc', 'music_videos', "
            "'released', 'best_of', 'worst_of', 'stems', or 'other'"
        ),
    )


class TabSection(BaseModel):
    """One parsed secondary tab, exposed as a switchable content mode.

    ``misc`` / ``music_videos`` entries also remain in the flat
    ``Artist.misc_entries`` list for backward compatibility — clients that
    understand ``tabs`` should prefer it as the uniform surface.
    """
    kind: str = Field(
        ...,
        description=(
            "Tab kind: 'misc' | 'music_videos' | 'released' | 'best_of' | "
            "'worst_of' | 'stems' | 'other'"
        ),
    )
    name: str = Field(..., description="Original tab display name (may include emoji)")
    entries: list[MiscEntry] = Field(default_factory=list)


class TrackerEntry(BaseModel):
    """One row of the TrackerHub master sheet — a discoverable artist tracker."""

    name: str
    url: str
    credit: str | None = None
    best: bool = False
    up_to_date: bool | None = None
    working_links: bool | None = None


class Notice(BaseModel):
    """An announcement notice extracted from a tracker header."""
    text: str = Field(..., description="Notice display text")
    link: str | None = Field(None, description="Associated URL (if any)")
    kind: str = Field("info", description="Notice kind: 'alert' for urgent warnings, 'info' for links/general")


class Artist(BaseModel):
    """Top-level artist with all parsed tracker data."""
    name: str = Field(..., description="Artist name")
    slug: str = Field(..., description="URL-safe identifier")
    source_url: str | None = Field(None, description="Original Google Sheets URL")
    eras: list[Era] = Field(default_factory=list)
    tracker_stats: TrackerStats | None = Field(None, description="Global tracker statistics")
    parse_metadata: ParseMetadata | None = Field(None, description="Parsing diagnostics")
    notices: list[Notice] = Field(default_factory=list, description="Announcement notices from tracker header")
    misc_entries: list[MiscEntry] = Field(
        default_factory=list,
        description="Entries from secondary Misc / Music Videos tabs (separate from eras)",
    )
    tabs: list[TabSection] = Field(
        default_factory=list,
        description=(
            "All parsed secondary tabs (misc, music_videos, released, "
            "best_of, worst_of, stems, other) as switchable content modes"
        ),
    )

    @property
    def total_songs(self) -> int:
        return sum(e.song_count for e in self.eras)

    @property
    def total_versions(self) -> int:
        return sum(e.version_count for e in self.eras)

    def dict(self, **kwargs):
        # Exclude ``eras`` from the native dump so the era subtree isn't
        # serialized twice (once natively here, then discarded and rebuilt via
        # ``era.dict()``). On a large tracker that redundant pass was real CPU.
        kwargs = _with_excluded(kwargs, "eras")
        d = super().model_dump(**kwargs)
        d["eras"] = [era.dict() for era in self.eras]
        d["total_songs"] = self.total_songs
        d["total_versions"] = self.total_versions
        return d

    def model_dump(self, **kwargs):
        return self.dict(**kwargs)


def _with_excluded(kwargs: dict, field: str) -> dict:
    """Return kwargs with *field* added to any caller-supplied ``exclude`` set."""
    kwargs = dict(kwargs)
    existing = kwargs.get("exclude")
    if existing is None:
        kwargs["exclude"] = {field}
    elif isinstance(existing, set):
        kwargs["exclude"] = existing | {field}
    elif isinstance(existing, dict):
        kwargs["exclude"] = {**existing, field: True}
    else:  # list/tuple/other iterable
        kwargs["exclude"] = set(existing) | {field}
    return kwargs


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
    r"(\d+)\s+([A-Za-z][A-Za-z /()]*?)(?=\s*\d|[^A-Za-z /()]|\Z)",
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
        # Normalize: strip "(s)" suffix (e.g. "Snippet(s)" → "snippet"),
        # including truncated variants from unbalanced parens ("(s", "(")
        if label.endswith("(s)"):
            label = label[:-3]
        elif label.endswith("(s"):
            label = label[:-2]
        elif label.endswith("("):
            label = label[:-1]
        label = label.strip()
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

# Patterns for extracting credit info from song name sub-lines.
# Trackers use either delimiter style — "(prod. X)" (Ye, Kendrick) or
# "[prod. X]" (Travis) — and hand-typed sheets mix the two by accident
# ("[prod. Travis Scott)"), so the closer is not required to match the
# opener. Every pattern is anchored on its keyword, so bracket support
# can't swallow a version tag like "[V1]" or "[Demo 8]".


def _credit_pattern(keyword: str) -> "re.Pattern[str]":
    """Build a credit regex matching `(kw value)` / `[kw value]` and mixes."""
    return re.compile(rf"[\(\[](?:{keyword})\s+(.+?)[\)\]]", re.IGNORECASE)


_FEAT_PATTERN = _credit_pattern(r"feat\.?|featuring|ft\.?")
_PROD_PATTERN = _credit_pattern(r"prod\.?")
_WITH_PATTERN = _credit_pattern(r"with")
_REF_PATTERN = _credit_pattern(r"ref\.?")
# Director credits sit on music-video and visual rows ("[dir. Dave Meyers]").
_DIR_PATTERN = _credit_pattern(r"dir\.?")


# Title continuations like "Vol. 2" / "Pt. II" / "Part Two" — a comma before
# these is part of one title ("Meet The Woo, Vol. 2"), not an alias separator.
_ALIAS_CONTINUATION_RE = re.compile(
    r"^(?:vol|pt|part|no)\.?\s*"
    r"(?:\d+|[ivxlc]+|one|two|three|four|five|six|seven|eight|nine|ten)$",
    re.IGNORECASE,
)


def _split_alt_aliases(text: str) -> list[str]:
    """Split a comma-separated alias list into individual aliases.

    Trackers write alt-name lines like "(Mollyworld, Balaclava Era)" meaning
    two aliases. Returns the parts only when the list looks like genuine
    aliases: every part >=3 chars and not a title continuation like "Vol. 2",
    and at least one part contains a letter — otherwise returns [text]
    unchanged. Keeps "Meet The Woo, Vol. 2" and "10,000 Days" whole while
    splitting numeric-alias lists like "14*29, 1429, Trippie Redd EP".
    """
    if "," not in text:
        return [text]
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 2:
        return [text]
    for p in parts:
        if len(p) < 3:
            return [text]
        if _ALIAS_CONTINUATION_RE.match(p):
            return [text]
    if not any(c.isalpha() for p in parts for c in p):
        return [text]
    return parts


class SongCredits(NamedTuple):
    """Structured result of :func:`parse_song_credits`."""

    title: str
    featuring: str | None
    producers: str | None
    collaboration: str | None
    refs: str | None
    director: str | None
    alt_titles: list[str]


def parse_song_credits(raw_name: str) -> SongCredits:
    """Parse a raw multi-line song name into title + structured credits.

    Raw names look like:
        10 in a Benz
        (with Go Getters) (feat. Rhymefest) (prod. Kanye West & Andy C.)
        (On 10 in a Benz)

    Credits in bracket form ("[prod. Allen Ritter]") parse identically —
    anything left over becomes an alt title.
    """
    text = raw_name

    # Extract all credit patterns from full text
    feat_matches = _FEAT_PATTERN.findall(text)
    prod_matches = _PROD_PATTERN.findall(text)
    with_matches = _WITH_PATTERN.findall(text)
    ref_matches = _REF_PATTERN.findall(text)
    dir_matches = _DIR_PATTERN.findall(text)

    # Remove credit patterns to get clean text
    cleaned = _FEAT_PATTERN.sub("", text)
    cleaned = _PROD_PATTERN.sub("", cleaned)
    cleaned = _WITH_PATTERN.sub("", cleaned)
    cleaned = _REF_PATTERN.sub("", cleaned)
    cleaned = _DIR_PATTERN.sub("", cleaned)

    # Split by newline: first line = title, rest = alt titles
    lines = [ln.strip() for ln in cleaned.split("\n")]
    title = lines[0].strip()

    # Remaining non-empty lines → alt titles
    alt_titles: list[str] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        # Strip wrapping parens: "(All I Have)" → "All I Have".
        # Parenthetical lines may list several aliases: "(A, B)" → two alts.
        if line.startswith("(") and line.endswith(")"):
            alt_titles.extend(_split_alt_aliases(line[1:-1].strip()))
        else:
            alt_titles.append(line)

    return SongCredits(
        title=title,
        featuring=", ".join(feat_matches) if feat_matches else None,
        producers=", ".join(prod_matches) if prod_matches else None,
        collaboration=", ".join(with_matches) if with_matches else None,
        refs=", ".join(ref_matches) if ref_matches else None,
        director=", ".join(dir_matches) if dir_matches else None,
        alt_titles=alt_titles,
    )


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

# OG Filename lead-in. Observed forms:
#   "OG Filename (Metadata): Bitch Im In The CLub NEW"
#   "OG Filename: Broke My Heart 1"
#   "OG Filename (?): Blazin' (KW Verse)"
#   "OG Filenames: Ohh Yeah Tellem RUFF &\nOhh Yeah Tellem RUFF 73.3"   (multi, '&' continues on next line)
#   "OG Filename KW - Where Are We Ref (1.15.13)"                       (no colon)
#   "OG Filename - Tel Aviv [melody demo 1]"                            (dash separator)
_OG_LEADIN_PATTERN = re.compile(
    r"OG Filenames?(?:\s*\([^)]*\))?\s*(?::\s*|-\s+|\s+)",
    re.IGNORECASE,
)

_OG_QUOTED_NAME_PATTERN = re.compile(r'\s*"([^"\n]+)"')

# Samples lead-in: everything from the keyword to the end of the line is one
# enumeration of sampled works ('Samples "A" by X and "B" by Y, "C" by Z.').
_SAMPLES_LEADIN_PATTERN = re.compile(r"\bSamples\b(?!\s+(?:from|of)\b)", re.IGNORECASE)

# Quoted title within a samples enumeration (quotes normalized to straight ").
_SAMPLE_TITLE_PATTERN = re.compile(r'"([^"\n]+)"')

# Pattern 2: "Samples Rufus & Chaka Khan's 'Ain't Nobody'". The closing single
# quote must sit on a word boundary so apostrophes inside the title survive.
_SAMPLE_POSSESSIVE_PATTERN = re.compile(
    r"Samples\s+([^\"'\n]+?)'s\s+'(.+?)'(?=[\s,.;)!?]|$)",
    re.IGNORECASE,
)

# Artist capture after "by", up to the next sample/separator.
_SAMPLE_ARTIST_PATTERN = re.compile(r"^\s*by\s+(.+)$", re.IGNORECASE | re.DOTALL)

_SMART_QUOTES = {
    "\u201c": '"', "\u201d": '"',   # \u201c \u201d
    "\u2018": "'", "\u2019": "'",   # \u2018 \u2019
}


def _normalize_quotes(text: str) -> str:
    for smart, straight in _SMART_QUOTES.items():
        text = text.replace(smart, straight)
    return text


def extract_og_filename(notes: str) -> str | None:
    """Extract the first OG Filename from notes text (legacy single-value API).

    Returns the filename string or None.
    """
    filenames = extract_og_filenames(notes)
    return filenames[0] if filenames else None


def _clean_og_name(name: str) -> str:
    return name.strip().rstrip("&").strip()


def _walk_og_lines(notes: str):
    """Yield (line_index, is_og, names) per line.

    A line whose stripped text starts with an OG lead-in is an OG line; a
    trailing '&' continues the filename list on the following line(s), which
    are also flagged as OG lines so stripping can drop the whole block.
    """
    lines = notes.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        m = _OG_LEADIN_PATTERN.match(stripped)
        if not m:
            yield i, False, []
            i += 1
            continue

        rest = stripped[m.end():].strip()
        # A quoted filename bounds the capture; otherwise take the line rest.
        quoted = _OG_QUOTED_NAME_PATTERN.match(rest)
        names = [quoted.group(1)] if quoted else ([rest] if rest else [])
        indices = [i]
        # '&' continuation: the next line holds another filename \u2014 unless it
        # is itself a labelled OG line, which the outer loop handles.
        while names and names[-1].rstrip().endswith("&") and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if _OG_LEADIN_PATTERN.match(nxt):
                break
            i += 1
            indices.append(i)
            if nxt:
                names.append(nxt)
        yield indices[0], True, [n for n in (_clean_og_name(x) for x in names) if n]
        for extra in indices[1:]:
            yield extra, True, []
        i += 1


def extract_og_filenames(notes: str) -> list[str]:
    """Extract every OG Filename from notes text, in order of appearance.

    Handles the singular and plural labels, parenthetical qualifiers,
    '&'-continued multi-line lists, and quoted filenames embedded in prose.
    """
    names: list[str] = []
    for _, is_og, line_names in _walk_og_lines(notes):
        names.extend(line_names)
    # Quoted filenames mentioned mid-sentence ("\u2026 the file included it's
    # OG Filename: \"X.mp3\" \u2026") \u2014 extract the quoted token only.
    for m in _OG_LEADIN_PATTERN.finditer(notes):
        line_start = notes.rfind("\n", 0, m.start()) + 1
        if notes[line_start:m.start()].strip():  # lead-in is mid-line
            quoted = _OG_QUOTED_NAME_PATTERN.match(notes, m.end())
            if quoted:
                names.append(_clean_og_name(quoted.group(1)))
    return names


def strip_og_filename_lines(notes: str) -> str:
    """Remove standalone 'OG Filename\u2026' lines (and their '&' continuation
    lines) from notes.

    The filenames are extracted into a structured field; leaving the lines in
    the notes text makes every client display them twice. Prose sentences
    that merely mention an OG filename are left intact.
    """
    lines = notes.split("\n")
    og_indices = {i for i, is_og, _ in _walk_og_lines(notes) if is_og}
    kept = [line for i, line in enumerate(lines) if i not in og_indices]
    return "\n".join(kept).strip()


def _clean_sample_artist(artist: str) -> str | None:
    """Trim enumeration/sentence noise from a captured artist string."""
    # Stop at a sentence boundary: a period after a word of 3+ letters
    # ('Chaka Khan. Leaked in\u2026'), so honorifics like 'Dr.' or initials like
    # 'J.' don't split the name. Commas/semicolons always end the artist.
    artist = re.split(r"(?<=\w\w\w)\.\s", artist)[0]
    artist = re.split(r"[,;]", artist)[0]
    # Drop trailing separators and dangling conjunctions left by slicing at
    # the next quoted title ('Mobb Deep and ' \u2192 'Mobb Deep').
    artist = artist.strip().rstrip(",;.").strip()
    artist = re.sub(r"\s+and$", "", artist, flags=re.IGNORECASE)
    # Strip trailing sentence noise. These handle cases like "George Benson
    # and the Common vs. Kanye\u2026" where the capture ran into prose. The "and"
    # strip is a heuristic that may affect compound band names; "&"-joined
    # names are unaffected.
    artist = re.sub(r"\s+and\s+.+$", "", artist, flags=re.IGNORECASE).strip()
    artist = re.sub(r"\s+vs\.?\s*.*$", "", artist, flags=re.IGNORECASE).strip()
    artist = re.sub(r"\s+feat\.?(\s+.+)?$", "", artist, flags=re.IGNORECASE).strip()
    # Prose continuation ('CyHi from his 2014 mixtape …') is commentary, not
    # part of the artist name.
    artist = re.sub(r"\s+from\s+(?:his|her|their|the)\b.*$", "", artist, flags=re.IGNORECASE).strip()
    artist = artist.rstrip(",;.").strip()
    # An implausibly long "artist" means the capture ran into prose.
    if len(artist) > 60:
        return None
    return artist or None


def _format_sample(song: str, artist: str | None) -> str:
    return f"{song} \u2014 {artist}" if artist else song


def extract_samples(notes: str) -> list[str]:
    """Extract sampled works from notes text.

    Handles multiple samples per enumeration ('Samples "A" by X and "B" by Y,
    "C" by Z.') and smart quotes. Returns clean strings without quote
    characters, e.g. ['Got Money \u2014 Lil Wayne'].
    """
    text = _normalize_quotes(notes)
    results: list[str] = []

    for lead in _SAMPLES_LEADIN_PATTERN.finditer(text):
        # One enumeration runs to the end of the line.
        end = text.find("\n", lead.end())
        segment = text[lead.end():end if end != -1 else len(text)]

        titles = list(_SAMPLE_TITLE_PATTERN.finditer(segment))
        if titles:
            prev_end = 0
            for i, title_match in enumerate(titles):
                # The lead-in and each further title must sit close to the
                # previous one \u2014 quoted phrases later in a prose sentence are
                # quotations, not sample titles.
                gap = segment[prev_end:title_match.start()]
                if i == 0:
                    if len(gap) > 50:
                        break
                elif len(gap) > 60 or not re.search(r"(?:,|;|\band\b|&)\s*$", gap, re.IGNORECASE):
                    break
                song = title_match.group(1).strip()
                if len(song) > 80:
                    break
                # Text between this title and the next holds the optional
                # "by Artist" clause \u2014 slicing here is what keeps one
                # sample's artist from swallowing the next sample.
                tail_end = titles[i + 1].start() if i + 1 < len(titles) else len(segment)
                tail = segment[title_match.end():tail_end]
                artist_match = _SAMPLE_ARTIST_PATTERN.match(tail.strip())
                artist = _clean_sample_artist(artist_match.group(1)) if artist_match else None
                results.append(_format_sample(song, artist))
                prev_end = title_match.end()
        else:
            # Pattern 2: Samples Artist's 'Song'
            possessive = _SAMPLE_POSSESSIVE_PATTERN.search(
                text[lead.start():end if end != -1 else len(text)]
            )
            if possessive:
                artist = possessive.group(1).strip()
                song = possessive.group(2).strip()
                results.append(_format_sample(song, artist or None))

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
