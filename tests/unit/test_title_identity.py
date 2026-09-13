"""Song identity from titles and alt titles (2026-09-13 review).

Versions of one song must group together, and a name cell must not lose an alt
title to the credit parser. Both were visible in the iOS version picker: Ye's
"Touch The Sky" / "Touch the Sky" were two songs, and one Precious version
showed "with Child, Stay On Em" as a collaboration.
"""

from __future__ import annotations

from src.models import Era, Section, Song, SongVersion
from src.parser import _add_version_to_era, _reconcile_title_misreads


def _era(*songs: Song) -> Era:
    return Era(name="E", sections=[Section(name="", songs=list(songs))])


class TestGroupingIgnoresCaseAndPunctuation:
    def _group(self, *names: str) -> Era:
        era = Era(name="E")
        index: dict = {}
        for name in names:
            _add_version_to_era(era, SongVersion(name=name), index)
        return era

    def test_case_variants_are_one_song(self):
        era = self._group("Touch The Sky [V1]", "Touch the Sky [V2]", "TOUCH THE SKY")
        songs = era.sections[0].songs
        assert len(songs) == 1
        assert songs[0].base_name == "Touch The Sky"  # first spelling wins
        assert len(songs[0].versions) == 3

    def test_punctuation_variants_are_one_song(self):
        era = self._group("HITLER YE AND JESUS", "HITLER, YE, AND JESUS")
        assert len(era.sections[0].songs) == 1

    def test_different_titles_stay_apart(self):
        era = self._group("Touch The Sky", "Touch The Sky (Remix)")
        assert len(era.sections[0].songs) == 2


class TestWithLineReadAsCredit:
    def _precious(self, misread: SongVersion) -> Era:
        sibling = SongVersion(name="Precious [V1]", alt_titles=["Hands Down", "Stay On Em", "With Child"])
        return _era(Song(base_name="Precious", song_key="precious", versions=[sibling, misread]))

    def test_alias_line_is_restored_as_alt_titles(self):
        misread = SongVersion(name="Precious [V23]", collaboration="Child, Stay On Em", featuring="Dem Jointz")
        _reconcile_title_misreads([self._precious(misread)])
        assert misread.collaboration is None
        assert misread.alt_titles == ["With Child", "Stay On Em"]
        assert misread.featuring == "Dem Jointz"

    def test_a_real_collaboration_is_untouched(self):
        collab = SongVersion(name="Precious [V24]", collaboration="Eminem")
        _reconcile_title_misreads([self._precious(collab)])
        assert collab.collaboration == "Eminem"
        assert collab.alt_titles == []

    def test_partly_matching_names_are_left_alone(self):
        # "With Child" matches, "JID" is no name in the family: still a credit.
        collab = SongVersion(name="Precious [V25]", collaboration="Child, JID")
        _reconcile_title_misreads([self._precious(collab)])
        assert collab.collaboration == "Child, JID"


class TestCommaTitleSplitIntoAliases:
    def test_known_title_is_rejoined(self):
        split = SongVersion(name="Kill My Vibe", alt_titles=["Bitch", "Don't Kill My Vibe"])
        released = SongVersion(name="Bitch, Don't Kill My Vibe")
        era = _era(
            Song(base_name="Kill My Vibe", song_key="kill my vibe", versions=[split]),
            Song(base_name="Bitch, Don't Kill My Vibe", song_key="bitch dont kill my vibe", versions=[released]),
        )
        _reconcile_title_misreads([era])
        assert split.alt_titles == ["Bitch, Don't Kill My Vibe"]

    def test_genuine_alias_lists_stay_split(self):
        aliases = SongVersion(name="Track", alt_titles=["Mollyworld", "Balaclava Era", "Other"])
        _reconcile_title_misreads([_era(Song(base_name="Track", song_key="track", versions=[aliases]))])
        assert aliases.alt_titles == ["Mollyworld", "Balaclava Era", "Other"]
