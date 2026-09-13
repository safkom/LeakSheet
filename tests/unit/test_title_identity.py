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


class TestCreditGroupRegexIsLinear:
    """SonarQube S5852, confirmed: a name cell with an unclosed "(" followed by
    repeated ", <newline>" lines made _CREDIT_GROUP_RE backtrack exponentially —
    2,000 characters did not finish in 15 s. Tracker cells are third-party and
    `re` holds the GIL, so one such cell stalled the whole worker."""

    def test_unclosed_wrapped_list_returns_quickly(self):
        import time

        from src.models import parse_song_credits

        raw = "Title\n(prod. A" + ",  \n  B" * 3000
        start = time.perf_counter()
        parse_song_credits(raw)
        assert time.perf_counter() - start < 1.0

    def test_wrapped_credit_lists_still_parse(self):
        from src.models import parse_song_credits

        # Wrapped after a separator: one group, as before the possessive rewrite.
        assert parse_song_credits("Song\n(prod. \nLondon On Da Track)").producers == "London On Da Track"
        wrapped = parse_song_credits("Song\n(prod. BoogzDaBeast,\nNascent)")
        assert wrapped.producers == "BoogzDaBeast, Nascent"
