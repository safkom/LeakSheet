"""LeakSheet — Configuration and path management."""

from pathlib import Path

# Project root directory
ROOT_DIR = Path(__file__).resolve().parent.parent

# Default trackers directory
TRACKERS_DIR = ROOT_DIR / "Trackers"

# Known tracker files and their artist names
KNOWN_TRACKERS: dict[str, str] = {
    "Baby Keem Music Tracker - Google Drive": "Baby Keem",
    "Kendrick Lamar Music Tracker - Google Drive": "Kendrick Lamar",
    "Playboi Carti Tracker [Currently in Use] - Google Drive": "Playboi Carti",
    "Ye Tracker - Google Drive": "Ye",
}


def discover_trackers(trackers_dir: Path | None = None) -> list[tuple[str, Path]]:
    """Discover all tracker files in the given directory.

    Returns list of (artist_name, sheet_html_path) tuples.
    """
    directory = trackers_dir or TRACKERS_DIR
    results = []

    for tracker_name, artist_name in KNOWN_TRACKERS.items():
        sheet_path = directory / f"{tracker_name}_files" / "sheet.html"
        if sheet_path.exists():
            results.append((artist_name, sheet_path))

    # Also discover any unknown tracker directories
    if directory.exists():
        for child in sorted(directory.iterdir()):
            if child.is_dir() and child.name.endswith("_files"):
                sheet_path = child / "sheet.html"
                if sheet_path.exists():
                    base_name = child.name.removesuffix("_files")
                    if base_name not in KNOWN_TRACKERS:
                        # Use the directory name as artist name
                        artist_name = base_name.replace(" - Google Drive", "").strip()
                        results.append((artist_name, sheet_path))

    return results


# Column name normalization — maps various header text to canonical field names.
# Covers 400+ tracker variants observed in the wild.
COLUMN_ALIASES: dict[str, str] = {
    # Core columns (present in nearly all trackers)
    "era": "era",
    "name": "name",
    "title": "name",              # Billie Eilish, Childish Gambino, Travis Scott
    "song name": "name",          # XXXTENTACION
    "song title": "name",
    "notes": "notes",
    "notes & information": "notes",
    "track number / info": "notes",  # Yuno Miles
    "info": "notes",
    "description": "notes",

    # Track length variants
    "track length": "track_length",
    "length": "track_length",      # Billie Eilish, Gucci Mane, etc.
    "track duration": "track_length",
    "duration": "track_length",

    # Dates
    "file date": "file_date",
    "creation date": "file_date",  # Kid Cudi
    "date created": "file_date",
    "year": "file_date",           # Avicii
    "leak date": "leak_date",
    "release date": "leak_date",   # Gucci Mane, Yuno Miles
    "obtained on:": "leak_date",   # Wu-Tang Clan
    "obtained on": "leak_date",

    # Availability
    "available length": "available_length",
    "currently available": "available_length",  # Kid Cudi, Chief Keef
    "available?": "available_length",             # Yung Lean
    "what's available?": "available_length",      # Travis Scott
    "available": "available_length",
    "song status": "available_length",            # XXXTENTACION
    "status": "available_length",
    "availability": "available_length",          # Lil Uzi Vert
    "portion": "available_length",                # Template variant

    # Quality
    "quality": "quality",

    # Links
    "link(s)": "links",
    "links": "links",
    "link": "links",
    "download(s)": "links",       # XXXTENTACION
    "downloads": "links",
    "download": "links",
    "og link(s)": "links",        # XXXTENTACION (secondary links)

    # Streaming (treated as availability info or skipped)
    "streaming": "streaming",
    "streaming?": "streaming",
    "in circulation": "available_length",  # Yung Lean

    # Type variants
    "type": "type",
    "track type": "type",          # XXXTENTACION
    "song type": "type",

    # Recording date variants
    "date of recording": "date_of_recording",  # Carti
    "recording date": "date_of_recording",      # Gucci Mane
}
