"""A superset hub tab after a subset tab merges only the songs main lacks."""

import pytest

import src.fetcher as fetcher
from src.models import Artist, Era, Section, Song, SongVersion
from src.fetcher import PhaseTimer, _aggregate_hub_workbook


def _artist(names: list[str]) -> Artist:
    songs = [Song(base_name=n, versions=[SongVersion(name=n)]) for n in names]
    return Artist(name="X", slug="x", eras=[Era(name="E", sections=[Section(songs=songs)])])


@pytest.mark.asyncio
async def test_superset_tab_after_subset_merges_only_new_songs(monkeypatch):
    async def fake_fetch(url, gid, title, **_kw):
        return ("x", gid)

    parsed = {"a": _artist(["One"]), "b": _artist(["One", "Two"])}
    monkeypatch.setattr(fetcher, "_fetch_gid_page", fake_fetch)
    monkeypatch.setattr(fetcher, "parse_sheet", lambda html, *_a: parsed[html])

    artist = _artist(["Zero"])
    total = await _aggregate_hub_workbook(
        artist, [("a", "Tab A"), ("b", "Tab B")], "u", "T",
        client=None, timeout=5, cache_ttl=0, use_cache=False, t=PhaseTimer(),
    )
    names = [s.base_name for e in artist.eras for sec in e.sections for s in sec.songs]
    assert sorted(names) == ["One", "Two", "Zero"]
    assert total == 2
