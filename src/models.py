"""LeakSheet — Data models for music tracker parsing."""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Badge(str, Enum):
    """Song badge / emoji classification."""
    BEST = "best"          # ⭐ ⭐️
    SPECIAL = "special"    # ✨
    WORST = "worst"        # 🗑️
    GRAIL = "grail"        # 🏆
    WANTED = "wanted"      # 🏅 🥇


# Mapping from emoji characters → Badge enum
EMOJI_TO_BADGE: dict[str, Badge] = {
    "⭐": Badge.BEST,
    "⭐️": Badge.BEST,
    "\u2b50": Badge.BEST,       # ⭐ (star)
    "\u2b50\ufe0f": Badge.BEST, # ⭐️ (star + variation selector)
    "✨": Badge.SPECIAL,
    "🗑️": Badge.WORST,
    "🗑": Badge.WORST,
    "🏆": Badge.GRAIL,
    "🏅": Badge.WANTED,
    "🥇": Badge.WANTED,
}

# Regex to detect and strip leading badge emojis from song names
BADGE_EMOJI_PATTERN = re.compile(
    r"^[\s]*(⭐️|⭐|✨|🗑️|🗑|🏆|🏅|🥇)[\s]*"
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
    name: str = Field(..., description="Full display name including version tag")
    version_tag: Optional[str] = Field(None, description="Version identifier, e.g. 'V1', 'V2', 'Alt.'")
    badge: Optional[Badge] = Field(None, description="Emoji badge classification")
    notes: Optional[str] = Field(None, description="Description/history text")
    track_length: Optional[str] = Field(None, description="Duration, e.g. '3:14'")
    file_date: Optional[str] = Field(None, description="Date the file was created")
    leak_date: Optional[str] = Field(None, description="Date the version leaked")
    available_length: Optional[str] = Field(None, description="Full/Partial/Snippet/etc.")
    quality: Optional[str] = Field(None, description="CD Quality/High Quality/etc.")
    links: list[str] = Field(default_factory=list, description="Download/reference URLs")
    # Carti-specific fields
    date_of_recording: Optional[str] = Field(None, description="Date of recording (Carti tracker)")
    type: Optional[str] = Field(None, description="Song type (Carti tracker)")


class Song(BaseModel):
    """A logical song that may have multiple versions."""
    base_name: str = Field(..., description="Song name without version tags or badges")
    versions: list[SongVersion] = Field(default_factory=list)

    @property
    def badge(self) -> Optional[Badge]:
        """Return the badge from any version (badges are per-song semantically)."""
        for v in self.versions:
            if v.badge is not None:
                return v.badge
        return None


class Era(BaseModel):
    """An album era / creative period containing songs."""
    name: str = Field(..., description="Era/album name")
    description: Optional[str] = Field(None, description="Historical context paragraph")
    stats_raw: Optional[str] = Field(None, description="Raw stats string, e.g. '3 OG File(s)...'")
    songs: list[Song] = Field(default_factory=list)

    @property
    def song_count(self) -> int:
        return len(self.songs)

    @property
    def version_count(self) -> int:
        return sum(len(s.versions) for s in self.songs)


class Artist(BaseModel):
    """Top-level artist with all parsed tracker data."""
    name: str = Field(..., description="Artist name")
    slug: str = Field(..., description="URL-safe identifier")
    source_url: Optional[str] = Field(None, description="Original Google Sheets URL")
    eras: list[Era] = Field(default_factory=list)

    @property
    def total_songs(self) -> int:
        return sum(e.song_count for e in self.eras)

    @property
    def total_versions(self) -> int:
        return sum(e.version_count for e in self.eras)


def extract_badge(name: str) -> tuple[Optional[Badge], str]:
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


def extract_version_tag(name: str) -> tuple[Optional[str], str]:
    """Extract version tag from a song name.

    Returns (version_tag, base_name) where base_name has the tag stripped.
    """
    match = VERSION_TAG_PATTERN.search(name)
    if match:
        tag = match.group(1)
        # Remove the [Vx] portion to get the base name
        base = name[:match.start()].strip() + name[match.end():].strip()
        base = base.strip()
        return tag, base
    return None, name.strip()


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")
