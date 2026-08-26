"""LeakSheet — Data models for music tracker parsing."""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

from pydantic import BaseModel, Field, computed_field


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

# Version tags like [V1], [Alt.], [Radio Mix], [MASTER] — form list:
# docs/decisions.md::models.py::VERSION_TAG_PATTERN
VERSION_TAG_PATTERN = re.compile(
    r"\[("
    r"[Vv]\d+(?:-[Vv]?\d+|-[Vv]?\?)?"  # V1, V1-V3, V2-V25, V1-V?, V2-V?
    r"|[Vv]\?"                           # V?
    r"|Alt\.?"                           # Alt, Alt.
    r"|Radio Mix"
    r"|Unfinished"
    # "Master File" before "MASTER" only for readability — the alternation
    # backtracks either way, but the shorter branch reads like it wins.
    r"|Master File"
    r"|MASTER"
    r"|CD VERSION"
    r"|Album"
    r"|Clean"
    r"|Song \d+"                         # Song 1, Song 2
    # Added 2026-08: the families below account for ~2,400 rows across the
    # cached trackers. Leaving them out did two things, not one — the tag
    # stayed in the displayed title AND, because _add_version_to_era groups on
    # the tag-stripped name, "90210 [Demo 8]" and "90210 [Demo 9]" became two
    # separate songs instead of two versions of one.
    r"|Demo(?:\s+\d+)?"                  # Demo, Demo 1 … Demo 45
    r"|OG File"
    r"|Instrumental"
    r"|Rough Mix"
    r"|Final Mix(?:\s+\d+)?"             # Final Mix, Final Mix 2
    r"|Final"
    r"|Remix"
    r"|Mix [A-Z]\b"                      # Mix A, Mix B
    r"|Live"
    r")\]",
    re.IGNORECASE,
)

# Version-tag ordering. Sheet order is row order, which puts [Demo 10] next to
# [Demo 1] and scatters an era's numbered takes; there was no sort at all
# before. Rank groups the families, the number orders within one, and the
# original index keeps everything else stable.
_VERSION_FAMILY_ORDER: list[tuple[str, "re.Pattern[str]"]] = [
    ("v", re.compile(r"^v\s*(\d+)", re.IGNORECASE)),
    ("demo", re.compile(r"^demo(?:\s+(\d+))?$", re.IGNORECASE)),
    ("song", re.compile(r"^song\s+(\d+)$", re.IGNORECASE)),
    ("mix", re.compile(r"^(?:final\s+mix|rough\s+mix|radio\s+mix|mix)\s*(\d+)?", re.IGNORECASE)),
]
_VERSION_FAMILY_RANK = {name: i for i, (name, _) in enumerate(_VERSION_FAMILY_ORDER)}
# Untagged and unrecognised tags sort after every recognised family, in sheet
# order — inventing an order for them would be worse than leaving them alone.
_VERSION_FAMILY_FALLBACK = len(_VERSION_FAMILY_ORDER)


def version_sort_key(version_tag: str | None, index: int) -> tuple[int, int, int]:
    """Sort key for one version of a song: (family, number, sheet order)."""
    if not version_tag:
        return (_VERSION_FAMILY_FALLBACK, 0, index)
    tag = version_tag.strip()
    for name, pattern in _VERSION_FAMILY_ORDER:
        m = pattern.match(tag)
        if m:
            number = int(m.group(1)) if m.lastindex and m.group(1) else 0
            return (_VERSION_FAMILY_RANK[name], number, index)
    return (_VERSION_FAMILY_FALLBACK, 0, index)


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
    preview_date: str | None = Field(
        None,
        description="When a snippet was first previewed. Distinct from "
                    "leak_date: a preview predates, and often never becomes, a leak.",
    )
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
    full: int = Field(0, description="Number of full versions ('Full' wording)")
    total_full: int = Field(
        0,
        description="Number of full versions ('Total Full' wording, which "
                    "counts the OG files within it)",
    )
    tagged: int = Field(0, description="Number of tagged versions")
    partial: int = Field(0, description="Number of partial versions")
    snippets: int = Field(0, description="Number of snippets")
    stem_bounces: int = Field(0, description="Number of stem bounces")
    unavailable: int = Field(0, description="Number of unavailable songs")

    # Discography-style trackers count releases, not leak states:
    #   "18 Total / 4 Singles / 7 Album Track(s) / 2 Feature(s) / 3 Other"
    # None of those map onto the leak-status fields above — a Single is not a
    # Full. They are kept verbatim as {label: count} rather than as ~20 typed
    # fields that would be zero for every leak-status tracker (and would need
    # extending again the first time a tracker invents another label). Clients
    # render the tracker's own wording, which is also what its readers expect.
    release_types: dict[str, int] = Field(
        default_factory=dict,
        description="Release-type counts from discography-style stat blocks, "
                    "keyed by the sheet's own label (e.g. {'singles': 4})",
    )
    stated_total: int = Field(
        0,
        description="Total the sheet states outright ('18 Total'), as opposed "
                    "to the sum `total` derives from the leak-status fields",
    )

    # computed_field, not a plain @property + model_dump() override. Pydantic
    # v2 serialises a NESTED model through pydantic-core, which walks the
    # schema and never calls a Python-level override — so Artist.model_dump()
    # (what /sheet returns) dropped `total` entirely and no client ever saw
    # the corrected number.
    @computed_field
    @property
    def total(self) -> int:
        """Total song count from stats.

        Trackers use one of two wordings for the full count, and they do not
        mean the same thing. Plain "Full" is a peer of OG File; "Total Full"
        (the Carti-style header) already *contains* the OG files, so adding
        both inflated the era total by the OG count — 338 against 207 real
        versions on Die Lit. Verified against all eight Carti eras that report
        a non-zero OG File alongside Total Full: excluding og_files makes
        every one match its parsed version count exactly.

        A discography-style block states its own total outright and populates
        none of the leak-status fields, so deriving would return 0. Trust the
        stated number when there is one.
        """
        if self.stated_total:
            return self.stated_total
        if self.total_full:
            return (
                self.total_full + self.tagged + self.partial
                + self.snippets + self.stem_bounces + self.unavailable
            )
        return (
            self.og_files + self.full + self.tagged + self.partial
            + self.snippets + self.stem_bounces + self.unavailable
        )

    # `total` must be a computed_field, not a model_dump() override. Pydantic
    # v2 serialises a NESTED model through pydantic-core, which walks the
    # schema and never calls the Python-level override — so Artist.model_dump()
    # (what /sheet returns) dropped `total` entirely and no client ever saw the
    # corrected number.


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
        # See docs/decisions.md: these STAY on the wire even though
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
    duplicate_columns: list[str] = Field(
        default_factory=list,
        description=(
            "Header cells an alias DOES cover, whose canonical field a "
            "different column already claimed (a sheet with two 'Name' "
            "columns). Their values are dropped too, but no alias work can "
            "change that — kept apart from dropped_columns so the gap list "
            "stays readable"
        ),
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
    """One row of the ArtistGrid tracker registry — a discoverable artist tracker."""

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
# Decorative emoji trackers hang off stat labels ("🔗 616 Total Links",
# "⭐ 43 Best Of"). Shared with the parser, which has to recognise the same
# cells to tell an era header from the sheet's global stats footer.
EMOJI_RUN_RE = re.compile(
    r"[\U0001f300-\U0001f9ff\u2600-\u27bf\u2b50\ufe0f\u200d]+"
)

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
    cleaned = EMOJI_RUN_RE.sub("", raw)
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


# Labels consumed by the typed leak-status fields below. Anything else in a
# stats block is a release-type count and goes to EraStats.release_types
# verbatim, so a tracker inventing new wording is preserved, not silently
# dropped the way an exact-key lookup drops it.
_LEAK_STATUS_LABELS = frozenset({
    "og file", "og files", "full", "total full", "tagged",
    "partial", "partial / cut", "snippet", "snippets",
    "stem bounce", "stem bounces", "unavailable", "total",
})


def parse_era_stats(raw: str) -> EraStats:
    """Parse a raw era stats string into an EraStats model."""
    pairs = _extract_stat_pairs(raw)

    return EraStats(
        og_files=pairs.get("og file", pairs.get("og files", 0)),
        # Kept apart, not aliased — see EraStats.total.
        full=pairs.get("full", 0),
        total_full=pairs.get("total full", 0),
        tagged=pairs.get("tagged", 0),
        partial=_match_stat(pairs, ["partial", "partial / cut"]),
        snippets=pairs.get("snippet", pairs.get("snippets", 0)),
        stem_bounces=pairs.get("stem bounce", pairs.get("stem bounces", 0)),
        unavailable=pairs.get("unavailable", 0),
        stated_total=pairs.get("total", 0),
        release_types={
            label: count
            for label, count in pairs.items()
            if label not in _LEAK_STATUS_LABELS
        },
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

# Credits come in either delimiter style, and hand-typed sheets mix them, so
# the closer need not match the opener. Keyword anchoring is what keeps this
# off version tags like "[V1]". Why: docs/decisions.md.


# One bracketed group. It spans a newline ONLY where the line ends with a list
# separator ("," or "&"), because that is a wrapped credit list and nothing
# else: an alt title is never preceded by a dangling comma inside an open
# bracket.
#
# This used to refuse newlines outright, on the grounds that an unclosed
# "(prod. " would swallow the alt-title lines below it and only one row on
# Travis needed it. Measuring the corpus changed the trade: 2,422 of 54,923
# alt titles (4.4%) were credit strings that leaked in because a long producer
# or feature list wrapped across <br> lines, so the group never closed. The
# separator rule recovers those without the swallowing risk — a continuation
# line that does not follow a comma still terminates the group exactly as
# before.
#
# A dot joins the comma and ampersand for the same reason: the wrap often lands
# immediately after the keyword rather than inside the list — "(prod. \nLondon
# On Da Track)" — which left the title reading "… (prod." and the names sitting
# in alt_titles. 37 name cells corpus-wide. Widening what the group CAN match
# is safe on its own: take_group hands back any group whose first part is not a
# credit keyword completely untouched.
# Collapses any whitespace run, newlines included, unlike _INNER_SPACE_RE.
_WHITESPACE_RUN_RE = re.compile(r"\s+")

_CREDIT_GROUP_RE = re.compile(r"[\(\[]((?:[^)\]\n]|[,&.][^\S\n]*\n[^\S\n]*)*)[\)\]]")

# field name → the keyword that introduces it, separator included. Order is
# the match order, so nothing here may be a prefix of a later entry.
# "dir." sits on music-video and visual rows ("[dir. Dave Meyers]").
_CREDIT_FIELDS: list[tuple[str, str]] = [
    # "feat. X", "ft. X", "feat.Dc2trill", "featuring X". Same dot-or-space
    # rule the producers entry uses, so "Feature" and "ftw" cannot match while
    # a glued "feat.Name" can — 13 name cells carried the glued form and had
    # their feature credit read as part of the title.
    ("featuring", r"(?:feat|ft)(?:\.\s*|\s+)|featuring\s+"),
    # "prod. X", "Prod.by Bighead", "prod.SlimeOnTheTRack", "produced by X".
    # A dot OR whitespace must follow "prod", so a title beginning "Prodigy"
    # cannot match. "by" is consumed on a word boundary rather than requiring
    # whitespace after it: a truncated "(prod.by" with no name left the filler
    # word itself standing as the producer, 443 times across the corpus.
    # An "add. prod." / "co-prod." group opens with neither keyword, so
    # take_group handed the whole thing back and the credit stayed inside the
    # title — 145 cells corpus-wide, A$AP Rocky's entire Purple Swag family
    # among them. Folded into `producers` rather than given a field of its own:
    # a new field costs a model change and a decode on every client for a
    # distinction the sheets themselves make inconsistently.
    ("producers",
     r"(?:add(?:itional)?\.?\s+|co-?\s*)?prod(?:uced|uction)?(?:\.\s*|\s+)(?:by\b\s*)?"),
    ("collaboration", r"with\s+|w/\s*"),
    ("refs", r"ref(?:erence)?\.?\s+"),
    ("director", r"dir(?:ected)?\.?(?:\s+by\b)?\s+"),
]

# Anchored at the start of a part: a keyword only counts where a credit can
# begin (right after the opener, or after a ';'/',' separator). That is what
# keeps this off version tags like "[V1]" and off "(Remix)".
_CREDIT_PART_RE = re.compile(
    "|".join(f"(?P<{field}>{pattern})" for field, pattern in _CREDIT_FIELDS),
    re.IGNORECASE,
)

# Runs of horizontal whitespace left behind where a group was removed.
_INNER_SPACE_RE = re.compile(r"[^\S\n]{2,}")


def _split_credit_parts(body: str) -> list[str]:
    """Split a credit-group body at each ';' or ',' that a keyword follows.

    Trackers mix conventions: the Ye sheet writes one group per credit
    ("(ref. X) (feat. Y)"), Travis packs several into one
    ("(ref. X; feat. Y & Z)"). Splitting only when a keyword follows keeps a
    comma inside a name list where it belongs — "(prod. A, B)" is one credit
    with two producers, not two credits.
    """
    parts: list[str] = []
    start = 0
    for sep in re.finditer(r"[;,]\s*", body):
        if _CREDIT_PART_RE.match(body, sep.end()):
            parts.append(body[start:sep.start()])
            start = sep.end()
    parts.append(body[start:])
    return [p.strip() for p in parts if p.strip()]


# Strips the redundant "AKA:" label — see docs/decisions.md::models.py::ALIAS_LABEL_RE
_ALIAS_LABEL_RE = re.compile(r"^\s*a\.?k\.?a\.?\s*[:\-–]?\s+", re.IGNORECASE)


def _strip_alias_label(text: str) -> str:
    """Drop a redundant "AKA:" lead-in from an alias. Never empties the value."""
    stripped = _ALIAS_LABEL_RE.sub("", text, count=1).strip()
    return stripped or text.strip()


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


# Fields safe to harvest from an UNBRACKETED line. "collaboration" is excluded
# on purpose: its keyword is "with", and plenty of songs are titled "With Or
# Without You". Inside brackets "(with Go Getters)" is unambiguous; bare, it is
# not, and guessing there invents a credit and destroys a title.
_BARE_CREDIT_FIELDS = frozenset({"featuring", "producers", "refs", "director"})


# An opening bracket the line never closes. Maintainers leave these behind
# constantly — see _harvest_bare_credit.
_UNCLOSED_OPENER_RE = re.compile(r"^[\(\[]\s*")


def _harvest_bare_credit(line: str, collected: dict[str, list[str]]) -> bool:
    """Route a credit line no bracketed group claimed into *collected*.

    Returns True if it was a credit.

    Two shapes reach here. Plenty of sheets write the credit as its own line
    with no brackets at all — "Prod.by Bighead", "ref. MNEK". Requiring
    brackets left 1,312 of these sitting in alt_titles across the captured
    corpus, where they read as alternative song titles and the credit was
    simply lost.

    The second shape is a bracket that was opened and never closed:
    "(prod.SlimeOnTheTRack", "[Prod.Swagg B", "(prod. BoogzDaBeast, Nascent,
    RONNY J, MIKE DEAN,". _CREDIT_GROUP_RE needs the closer, so the whole line
    fell through as an alt title — 1,086 name cells corpus-wide, leaving 608
    alt_titles that are really credits, 505 of them on one tracker.

    The keyword must OPEN the line, the same rule bracketed groups already
    follow, so a real title that merely mentions a producer later is untouched.
    A stripped opener also lifts the "collaboration" exclusion: "with" is
    ambiguous bare (plenty of songs are titled "With Or Without You") but not
    after a bracket, which is the same reasoning that lets closed groups
    harvest it.
    """
    text = line.strip()
    opener = _UNCLOSED_OPENER_RE.match(text)
    bracketed = bool(opener) and not text.endswith((")", "]"))
    if bracketed:
        text = text[opener.end():]
    keyword = _CREDIT_PART_RE.match(text)
    if keyword is None:
        return False
    if not bracketed and keyword.lastgroup not in _BARE_CREDIT_FIELDS:
        return False
    # An unclosed list often ends mid-separator ("A, B, MIKE DEAN," / "X &").
    # That dangling separator is truncation, not a name.
    # An unclosed list often ends mid-separator ("A, B, MIKE DEAN," / "X &").
    # That dangling separator is truncation, not a name.
    value = _WHITESPACE_RUN_RE.sub(" ", text[keyword.end():]).strip().rstrip(")] ,&")
    if value:
        collected.setdefault(keyword.lastgroup, []).append(value)
    # True even with nothing to store. A line that is only "(prod.by" names no
    # producer, but it is still a credit line, not an alternative song title —
    # sending it back would put "(prod.by" in alt_titles and, because a row
    # with no credit and no other data reads as a section label, drop the song
    # with it.
    return True


def parse_song_credits(raw_name: str) -> SongCredits:
    """Parse a raw multi-line song name into title + structured credits.

    Raw names look like:
        10 in a Benz
        (with Go Getters) (feat. Rhymefest) (prod. Kanye West & Andy C.)
        (On 10 in a Benz)

    Credits in bracket form ("[prod. Allen Ritter]") parse identically —
    anything left over becomes an alt title.
    """
    collected: dict[str, list[str]] = {}

    def take_group(match: "re.Match[str]") -> str:
        """Harvest one bracketed group's credits; return "" if it was one."""
        parts = _split_credit_parts(match.group(1))
        opener = _CREDIT_PART_RE.match(parts[0]) if parts else None
        # The keyword must open the group, exactly as it always had to. Without
        # that rule "(Some Title, prod. X)" would lose its title half, and
        # "(Remix)" / "[V1]" would have to be special-cased out.
        if opener is None:
            return match.group(0)
        for part in parts:
            keyword = _CREDIT_PART_RE.match(part)
            # Guaranteed non-None: _split_credit_parts only breaks where a
            # keyword follows, and parts[0] was just checked.
            if keyword is None:
                continue
            # A wrapped list carries the newline into the value.
            value = _WHITESPACE_RUN_RE.sub(" ", part[keyword.end():]).strip()
            if value and keyword.lastgroup:
                collected.setdefault(keyword.lastgroup, []).append(value)
        return ""

    cleaned = _CREDIT_GROUP_RE.sub(take_group, raw_name)
    # A removed group leaves a double space behind ("Title (feat. A) Remix").
    cleaned = _INNER_SPACE_RE.sub(" ", cleaned)

    def joined(field: str) -> str | None:
        values = collected.get(field)
        return ", ".join(values) if values else None

    # Split by newline: first line = title, rest = alt titles
    lines = [ln.strip() for ln in cleaned.split("\n")]
    title = lines[0].strip()

    # Remaining non-empty lines → alt titles
    alt_titles: list[str] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        # Multi-alias paren splitting — see docs/decisions.md::models.py::ALIAS_LABEL_RE
        if line.startswith("(") and line.endswith(")"):
            inner = _strip_alias_label(line[1:-1].strip())
            alt_titles.extend(_split_alt_aliases(inner))
        elif not _harvest_bare_credit(line, collected):
            alt_titles.append(_strip_alias_label(line))

    return SongCredits(
        title=title,
        featuring=joined("featuring"),
        producers=joined("producers"),
        collaboration=joined("collaboration"),
        refs=joined("refs"),
        director=joined("director"),
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

# OG Filename lead-in — observed forms: docs/decisions.md::models.py::_OG_LEADIN_PATTERN
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


def _clean_og_name(name: str) -> str:
    return name.strip().rstrip("&").strip()


def _is_og_listing(match: "re.Match[str]", rest: str) -> bool:
    """True when an OG lead-in actually introduces a filename.

    The lead-in accepts a bare space as its separator, because
    "OG Filename KW - Where Are We Ref (1.15.13)" is a real observed form. But
    that also matched prose — "OG Filenames are unknown for this track" —
    which was then stored as a filename AND deleted from the notes.

    An explicit ':' or '-' separator is always a listing. After a bare space,
    a filename starts like a filename: never with a lowercase word, which is
    what every prose continuation ("are…", "is…", "were…", "not…") does.
    """
    if not rest:
        return False
    if match.group(0).rstrip().endswith((":", "-")):
        return True
    return not rest[0].islower()


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
        if not _is_og_listing(m, rest):
            yield i, False, []
            i += 1
            continue
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
    # Trailing sentence-noise heuristic \u2014 see docs/decisions.md::models.py::artist-cleanup
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
