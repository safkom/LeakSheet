"""Small guards on attacker-reachable inputs: addresses, image types, colspan,
and era names that must stay unique."""
import pytest

from src.api import _is_raster_image
from src.models import Era
from src.parser import _MAX_COLSPAN, _disambiguate_era_names, _extract_table_lxml, _TableExtractor
from src.streaming import _ip_is_public


@pytest.mark.parametrize("ip,public", [
    ("8.8.8.8", True), ("2606:4700::1", True),
    ("10.0.0.1", False), ("127.0.0.1", False), ("169.254.169.254", False),
    ("100.64.0.1", False), ("100.100.100.200", False),  # CGNAT / shared space
    ("::1", False), ("fc00::1", False), ("::ffff:10.0.0.1", False), ("224.0.0.1", False),
    # IPv6 forms wrapping an IPv4 address: judged by the address inside.
    ("::a00:1", False), ("::127.0.0.1", False), ("64:ff9b::a00:1", False),
    ("64:ff9b::a9fe:a9fe", False), ("64:ff9b::808:808", True), ("::ffff:8.8.8.8", True),
])
def test_only_global_unicast_is_public(ip, public):
    assert _ip_is_public(ip) is public


@pytest.mark.parametrize("ct,ok", [
    ("image/jpeg", True), ("image/png; charset=binary", True), ("IMAGE/WEBP", True),
    ("image/svg+xml", False), ("text/html", False), ("", False),
])
def test_image_proxy_accepts_raster_types_only(ct, ok):
    assert _is_raster_image(ct) is ok


def test_era_names_come_out_unique():
    names = ["Foo (2)", "Foo", "Foo", "", ""]
    out = [e.name for e in _disambiguate_era_names([Era(name=n) for n in names])]
    assert len(set(out)) == len(out)
    assert out[:2] == ["Foo (2)", "Foo"]


def test_colspan_is_clamped_in_both_extractors():
    html = '<table><tr><td colspan="999999999">a</td><td>b</td></tr></table>'
    fast = _extract_table_lxml(html)
    slow = _TableExtractor()
    slow.feed(html)
    for rows in (fast, slow.rows):
        assert len(rows[0]) == _MAX_COLSPAN + 1
