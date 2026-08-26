"""Era cover art must come out of the parser as a URL something can fetch.

Self-hosted trackers serve covers from their own origin as "/assets/<sha>.jpg".
Those relative paths reached clients verbatim and could be fetched by nothing —
268 eras across the captured corpus. Two halves to the fix, and both are
needed: resolve the URL against the tab it came from, and let the image proxy
fetch from a host the backend already downloads sheet HTML from.
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

    def test_tracker_host_allowed_once_registered(self, monkeypatch):
        # The registry is module-global and this is a trust boundary, so the
        # host must not survive into the SSRF tests.
        import src.config as config
        monkeypatch.setattr(config, "_tracker_hosts", set())
        url = "https://selfhosttracker.net/assets/deadbeef.jpg"
        assert not _image_host_allowed(url)
        config.register_tracker_hosts(["https://selfhosttracker.net/"])
        assert _image_host_allowed(url)


class TestArtTabRelativeArt:
    """The Art tab overwrites era.art_url AFTER parse_sheet resolved it.

    parse_sheet ran _absolutize_era_art, then apply_art_tab_images put the raw
    "/assets/<sha>.jpg" straight back, so a self-hosted tracker with an Art tab
    still shipped covers nothing could fetch. Resolving in parse_art_tab fixes
    it for every caller rather than one call site.
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

    def test_applied_era_art_survives_the_art_tab(self):
        """End to end: the whole point is that apply_art_tab_images cannot
        reintroduce a relative URL."""
        from src.parser import apply_art_tab_images, parse_art_tab, parse_sheet
        artist = parse_sheet(RELATIVE_ART_TAB, "Selfhost", SOURCE)
        apply_art_tab_images(artist, parse_art_tab(self.ART_TAB, self.SOURCE))
        for era in artist.eras:
            assert era.art_url is None or urlparse(era.art_url).netloc


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

    def test_applied_end_to_end_gives_each_version_its_own_art(self):
        from src.models import Artist, Era
        from src.parser import apply_art_tab_images, parse_art_tab
        artist = Artist(name="Ye", slug="ye", eras=[
            Era(name="Donda [V1]"), Era(name="Donda [V2]"), Era(name="Donda [V3]"),
        ])
        apply_art_tab_images(artist, parse_art_tab(VERSIONED_ART_TAB))
        assert artist.eras[0].art_url == "https://cdn/v1-cover.jpg"
        assert artist.eras[1].art_url == "https://cdn/v2-cover.jpg"
        # V3 has no Art tab row: falls back to the base key rather than losing art.
        assert artist.eras[2].art_url == "https://cdn/v1-cover.jpg"
