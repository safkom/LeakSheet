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


def get_sheet_path(tracker_name: str) -> Path:
    """Get the sheet.html path for a tracker by its directory name."""
    return TRACKERS_DIR / f"{tracker_name}_files" / "sheet.html"


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


# Column name normalization — maps various header text to canonical field names
COLUMN_ALIASES: dict[str, str] = {
    "era": "era",
    "name": "name",
    "notes": "notes",
    "track length": "track_length",
    "file date": "file_date",
    "leak date": "leak_date",
    "available length": "available_length",
    "quality": "quality",
    "link(s)": "links",
    "links": "links",
    "link": "links",
    # Carti-specific
    "date of recording": "date_of_recording",
    "type": "type",
}
