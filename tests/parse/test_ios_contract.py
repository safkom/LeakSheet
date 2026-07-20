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


def _assert_non_null(d: dict, keys: list[str], ctx: str) -> None:
    for k in keys:
        assert k in d and d[k] is not None, f"{ctx}: {k!r} is null/missing — iOS decode would fail"


def _check_artist_payload(payload: dict) -> None:
    _assert_non_null(payload, ["name", "slug", "eras"], "Artist")
    for era in payload["eras"]:
        _assert_non_null(era, ["name", "sections"], f"Era {era.get('name')!r}")
        for sec in era["sections"]:
            _assert_non_null(sec, ["name", "songs"], f"Section in {era['name']!r}")
            for song in sec["songs"]:
                _assert_non_null(song, ["base_name", "versions"], f"Song in {era['name']!r}")
                assert song["versions"], f"Song {song['base_name']!r} has empty versions"
                for v in song["versions"]:
                    _assert_non_null(v, ["name"], f"Version of {song['base_name']!r}")
                    for s in v.get("sources") or []:
                        _assert_non_null(s, ["label", "url"], f"SourceRef on {v['name']!r}")
    for m in payload.get("misc_entries") or []:
        _assert_non_null(m, ["era_name", "name", "links", "source_tab"], f"MiscEntry {m.get('name')!r}")
    for n in payload.get("notices") or []:
        _assert_non_null(n, ["text"], "Notice")
    for t in payload.get("tabs") or []:
        _assert_non_null(t, ["kind", "name", "entries"], f"TabSection {t.get('name')!r}")
        for m in t["entries"]:
            _assert_non_null(m, ["era_name", "name", "links", "source_tab"], f"Tab entry {m.get('name')!r}")


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
