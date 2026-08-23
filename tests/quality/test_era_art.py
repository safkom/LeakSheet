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
