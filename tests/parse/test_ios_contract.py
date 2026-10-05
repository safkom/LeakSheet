"""The iOS hard-decode contract: fields that must NEVER be null/missing.

The Swift models declare these fields non-optional; pydantic mostly enforces
them structurally, but this test pins the contract at the SERIALIZED payload
level (what the app actually decodes), so a future model/serializer change that
starts emitting null for any of them fails here instead of bricking every
/sheet response in the app ("Failed to parse tracker data", no partial render):

  Artist.name/slug/eras · Era.name/sections · Section.name/songs
  Song.base_name/versions · SongVersion.name · MiscEntry.era_name/name/links/
  source_tab · SourceRef.label/url · Notice.text · TabSection.kind/name/entries
"""

from __future__ import annotations

from src.parser import parse_misc_tab, parse_sheet
from tests.conftest import read_synthetic
from tests.quality.invariants import ios_contract_violations


def _check_artist_payload(payload: dict) -> None:
    assert not ios_contract_violations(payload)


class TestIOSHardDecodeContract:
    def test_main_tab_payload(self):
        artist = parse_sheet(read_synthetic("main_tab"), "SynthWave")
        _check_artist_payload(artist.model_dump())

    def test_travis_style_payload(self):
        artist = parse_sheet(read_synthetic("travis_style"), "Astro")
        _check_artist_payload(artist.model_dump())

    def test_payload_with_misc_entries(self):
        artist = parse_sheet(read_synthetic("main_tab"), "SynthWave")
        artist.misc_entries.extend(parse_misc_tab(read_synthetic("misc_tab"), "misc"))
        _check_artist_payload(artist.model_dump())

    def test_degenerate_payload(self):
        # Even an empty parse must serialize a decodable envelope.
        artist = parse_sheet("", "Nobody")
        _check_artist_payload(artist.model_dump())
