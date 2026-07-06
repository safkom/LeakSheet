"""_infer_artist_name — tracker page titles → clean artist names.

The 2026-07-06 live census surfaced titles whose qualifiers FOLLOW the word
"Tracker" ("… Tracker [Official]", "… Tracker PUBLIC"); the suffix list only
handled qualifiers before it, so tracker cruft leaked into artist names shown
by the apps.
"""

import pytest

from src.fetcher import _infer_artist_name


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Documented behavior (regression guard)
        ("Ye Tracker - Google Drive", "Ye"),
        ("Baby Keem Music Tracker - Google Drive", "Baby Keem"),
        ("Playboi Carti Tracker [Currently in Use] - Google Drive", "Playboi Carti"),
        ("Updated Lil Uzi Vert Tracker - Google Drive", "Lil Uzi Vert"),
        ("Travis Scott Tracker 2.0", "Travis Scott"),
        # 2026-07-06 census failures: qualifier after "Tracker"
        ("Playboi Carti Tracker [Official] - Google Drive", "Playboi Carti"),
        ("Playboi Carti Tracker [Official]", "Playboi Carti"),
        ("Ye Tracker PUBLIC", "Ye"),
        ("Drake Tracker (reup 12.29.25) - Google Drive", "Drake"),
    ],
)
def test_infer_artist_name(title: str, expected: str) -> None:
    assert _infer_artist_name(title) == expected
