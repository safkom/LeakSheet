"""Era cover art must come out of the parser as a URL something can fetch.

Self-hosted trackers serve covers as "/assets/<sha>.jpg": the parser resolves them
against the tab they came from, and the image proxy fetches from that tracker's host
only when it is curated, never when it was harvested from the ArtistGrid feed.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from src.api import _image_host_allowed
from src.parser import parse_sheet

RELATIVE_ART_TAB = """
<html><head><title>Selfhost Tracker</title></head><body>
<table>
<tr><td>Era</td><td>Name</td><td>Notes</td><td>Length</td><td>Leak Date</td>
    <td>Available</td><td>Quality</td><td>Link(s)</td></tr>
<tr><td>2 Full<br>1 Snippet</td><td>Opening Era</td><td>(2020) (it begins)</td>
    <td></td><td></td><td></td><td></td>
    <td><img src="/assets/deadbeef.jpg"></td></tr>
<tr><td>Opening Era</td><td>First Track</td><td></td><td>3:00</td>
    <td>2020-01-01</td><td>Full</td><td>High Quality</td><td></td></tr>
</table></body></html>
"""

SOURCE = "https://selfhosttracker.net/preview/sheet/1"


class TestRelativeArtResolution:
    def test_relative_art_is_resolved_against_the_source(self):
        artist = parse_sheet(RELATIVE_ART_TAB, "Selfhost", SOURCE)
        art = artist.eras[0].art_url
        assert art == "https://selfhosttracker.net/assets/deadbeef.jpg"
        assert urlparse(art).netloc, "art URL must be absolute"

    def test_without_a_source_url_the_value_is_unchanged(self):
        # Many callers parse a local file and have no URL. They must keep
        # working rather than get a mangled path.
        artist = parse_sheet(RELATIVE_ART_TAB, "Selfhost")
        assert artist.eras[0].art_url == "/assets/deadbeef.jpg"

    def test_absolute_art_is_left_alone(self):
        tab = RELATIVE_ART_TAB.replace(
            '/assets/deadbeef.jpg', 'https://docs.google.com/sheets-images-rt/XYZ'
        )
        artist = parse_sheet(tab, "Selfhost", SOURCE)
        assert artist.eras[0].art_url == "https://docs.google.com/sheets-images-rt/XYZ"


class TestImageProxyHosts:
    @pytest.mark.parametrize("url", [
        "https://lh3.googleusercontent.com/abc",
        "https://img.youtube.com/vi/abc/0.jpg",
    ])
    def test_static_cdn_hosts_still_allowed(self, url):
        assert _image_host_allowed(url)

    def test_unknown_host_still_rejected(self):
        assert not _image_host_allowed("https://evil.example.com/a.jpg")

    def test_feed_registered_host_is_not_enough(self, monkeypatch):
        """The ArtistGrid feed is third-party. It may widen what /sheet fetches,
        but not what this endpoint — which answers any origin — hands back."""
        import src.config as config
        monkeypatch.setattr(config, "_tracker_hosts", set())
        monkeypatch.delenv("LEAKSHEET_EXTRA_SHEET_HOSTS", raising=False)
        url = "https://selfhosttracker.net/assets/deadbeef.jpg"
        config.register_tracker_hosts(["https://selfhosttracker.net/"])
        assert config.sheet_host_allowed("selfhosttracker.net")
        assert not _image_host_allowed(url)

    def test_seeded_self_hosted_tracker_is_allowed(self):
        # tylertracker.net serves 40 era covers from its own origin.
        assert _image_host_allowed("https://tylertracker.net/assets/deadbeef.jpg")

    def test_env_listed_host_is_allowed(self, monkeypatch):
        monkeypatch.setenv("LEAKSHEET_EXTRA_SHEET_HOSTS", "selfhosttracker.net")
        assert _image_host_allowed("https://selfhosttracker.net/assets/deadbeef.jpg")


class TestArtTabRelativeArt:
    """Art-tab images are resolved against the source URL in parse_art_tab.

    Resolving after parse_sheet let a raw "/assets/<sha>.jpg" reach the payload, so a
    self-hosted tracker with an Art tab shipped covers nothing could fetch.
    """

    ART_TAB = """
    <html><body><table>
    <tr><td>Era</td><td>Project Type</td><td>Image</td></tr>
    <tr><td>Opening Era</td><td>Front Cover</td>
        <td><img src="/assets/cafebabe.jpg"></td></tr>
    </table></body></html>
    """
    SOURCE = "https://selfhosttracker.net/preview/sheet/1"

    def test_relative_art_tab_image_is_resolved(self):
        from src.parser import parse_art_tab
        art = parse_art_tab(self.ART_TAB, self.SOURCE)
        assert list(art.values()) == ["https://selfhosttracker.net/assets/cafebabe.jpg"]

    def test_without_source_url_value_is_unchanged(self):
        from src.parser import parse_art_tab
        assert list(parse_art_tab(self.ART_TAB).values()) == ["/assets/cafebabe.jpg"]

    def test_absolute_art_tab_image_is_left_alone(self):
        from src.parser import parse_art_tab
        tab = self.ART_TAB.replace("/assets/cafebabe.jpg", "https://docs.google.com/x/Y")
        assert list(parse_art_tab(tab, self.SOURCE).values()) == ["https://docs.google.com/x/Y"]

    def test_art_tab_candidates_are_absolute(self):
        """End to end: an Art-tab candidate cannot reintroduce a relative URL."""
        from src.parser import art_tab_candidates, parse_art_tab, parse_sheet
        artist = parse_sheet(RELATIVE_ART_TAB, "Selfhost", SOURCE)
        for url in art_tab_candidates(artist, parse_art_tab(self.ART_TAB, self.SOURCE)).values():
            assert urlparse(url).netloc


# Ye's Art tab carries BOTH an "Art Type" column (the medium) and a "Project
# Type" column (the role), and names each version's cover separately. Two
# separate bugs collapsed onto the same symptom — every era wearing the wrong
# artwork — so both shapes are pinned here.
VERSIONED_ART_TAB = """
<html><body><table>
<tr><td>Era</td><td>Name</td><td>Notes</td><td>Designer</td><td>Art Type</td>
    <td>Image</td><td>Project Type</td><td>Use</td></tr>
<tr><td>Donda [V1]</td><td>Donda</td><td>notes</td><td>x</td><td>Digital</td>
    <td><img src="https://cdn/v1-promo.jpg"></td><td>Promo Art</td><td>Used</td></tr>
<tr><td>Donda [V1]</td><td>Donda</td><td>notes</td><td>x</td><td>Digital</td>
    <td><img src="https://cdn/v1-cover.jpg"></td><td>Front Cover</td><td>Used</td></tr>
<tr><td>Donda [V2]</td><td>Donda</td><td>notes</td><td>x</td><td>Digital</td>
    <td><img src="https://cdn/v2-cover.jpg"></td><td>Front Cover</td><td>Used</td></tr>
<tr><td>Good Ass Job (2018)</td><td>GAJ</td><td>notes</td><td>x</td><td>Digital</td>
    <td><img src="https://cdn/gaj-2018.jpg"></td><td>Front Cover</td><td>Used</td></tr>
</table></body></html>
"""


class TestArtTabColumnAndVersionKeys:
    def test_project_type_column_wins_over_art_type(self):
        """"Art Type" holds the medium (Digital/Scan), so it can never say
        "cover". Binding to it silently disabled the cover preference for every
        era on the tracker and each one fell back to its first-listed artwork."""
        from src.parser import parse_art_tab
        art = parse_art_tab(VERSIONED_ART_TAB)
        assert art["donda [v1]"] == "https://cdn/v1-cover.jpg", "must skip the Promo Art row"

    def test_each_version_keeps_its_own_cover(self):
        from src.parser import parse_art_tab
        art = parse_art_tab(VERSIONED_ART_TAB)
        assert art["donda [v1]"] == "https://cdn/v1-cover.jpg"
        assert art["donda [v2]"] == "https://cdn/v2-cover.jpg"

    def test_parenthetical_discriminator_is_kept(self):
        from src.parser import parse_art_tab
        assert parse_art_tab(VERSIONED_ART_TAB)["good ass job (2018)"] == "https://cdn/gaj-2018.jpg"

    def test_untagged_era_still_resolves_through_the_base_key(self):
        """An Art tab that tags its rows must still serve an era that doesn't."""
        from src.parser import parse_art_tab
        assert parse_art_tab(VERSIONED_ART_TAB)["donda"] == "https://cdn/v1-cover.jpg"

    def test_a_sibling_version_is_never_a_candidate(self):
        """The Ye case: the Art tab lists only "[V2]", but "[V1]" has its own cover.

        The version-stripped alias names ONE version's cover; offering it to a sibling
        replaced [V1]'s correct main-tab artwork with [V2]'s.
        """
        from src.models import Artist, Era
        from src.parser import art_tab_candidates, parse_art_tab
        tab = """
        <html><body><table>
        <tr><td>Era</td><td>Name</td><td>Project Type</td><td>Image</td></tr>
        <tr><td>Cruel Winter [V2]</td><td>Champions</td><td>Front Cover</td>
            <td><img src="https://cdn/cw-v2.jpg"></td></tr>
        </table></body></html>
        """
        artist = Artist(name="Ye", slug="ye", eras=[
            Era(name="Cruel Winter [V1]", art_url="https://cdn/cw-v1-inline.jpg"),
            Era(name="Cruel Winter [V2]", art_url="https://cdn/cw-v2-inline.jpg"),
        ])
        assert art_tab_candidates(artist, parse_art_tab(tab)) == {
            "Cruel Winter [V2]": "https://cdn/cw-v2.jpg",
        }

    def test_an_era_without_a_main_tab_cover_gets_no_candidate(self):
        """Nothing to compare against, so nothing proves the Art tab's image is its cover."""
        from src.models import Artist, Era
        from src.parser import art_tab_candidates, parse_art_tab
        artist = Artist(name="Ye", slug="ye", eras=[Era(name="Donda [V1]")])
        assert art_tab_candidates(artist, parse_art_tab(VERSIONED_ART_TAB)) == {}

    def test_untagged_eras_still_take_the_alias(self):
        from src.models import Artist, Era
        from src.parser import art_tab_candidates, parse_art_tab
        artist = Artist(name="Ye", slug="ye",
                        eras=[Era(name="Donda", art_url="https://cdn/inline.jpg")])
        assert art_tab_candidates(artist, parse_art_tab(VERSIONED_ART_TAB)) == {
            "Donda": "https://cdn/v1-cover.jpg",
        }

    def test_each_version_is_offered_its_own_art(self):
        from src.models import Artist, Era
        from src.parser import art_tab_candidates, parse_art_tab
        artist = Artist(name="Ye", slug="ye", eras=[
            Era(name=f"Donda [V{n}]", art_url=f"https://cdn/inline-v{n}.jpg") for n in (1, 2, 3)
        ])
        # V3 has no Art tab row, and V1's cover is not V3's.
        assert art_tab_candidates(artist, parse_art_tab(VERSIONED_ART_TAB)) == {
            "Donda [V1]": "https://cdn/v1-cover.jpg",
            "Donda [V2]": "https://cdn/v2-cover.jpg",
        }
