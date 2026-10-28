"""Only http(s) links leave the parser: apps open every link they get.

javascript:, file:, smb: and system-settings URLs crash SFSafariViewController or run
handlers through NSWorkspace, so each link-producing path drops them.
"""
import pytest

from src.parser import _clean_link, _split_links, parse_misc_tab, parse_sheet

GOOD = "https://pillows.su/f/0123456789abcdef0123456789abcdef"
BAD = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "file:///etc/passwd",
    "smb://host/share",
    "data:text/html,<b>x</b>",
    "x-apple.systempreferences:com.apple.preference.security",
    "mailto:a@b.test",
    "/relative/path",
    "ftp://host/file",
]


def _table(header: list[str], row: list[str]) -> str:
    cells = lambda r: "".join(f"<td>{c}</td>" for c in r)  # noqa: E731
    return f"<table><tr>{cells(header)}</tr><tr>{cells(row)}</tr></table>"


def _a(url: str) -> str:
    return f"<a href='{url}'>x</a>"


def _version(header: list[str], row: list[str]):
    return parse_sheet(_table(header, row), "Test").eras[0].songs[0].versions[0]


@pytest.mark.parametrize("bad", BAD)
def test_helpers_drop_non_http(bad):
    assert _clean_link(bad) == ""
    assert _split_links(bad) == []
    assert _split_links(f"{bad} {GOOD}") == [GOOD]
    wrapped = f"https://www.google.com/url?q={bad}&sa=D"
    assert _clean_link(wrapped) == ""


@pytest.mark.parametrize("bad", BAD)
def test_link_and_notes_columns(bad):
    v = _version(["Era", "Name", "Notes", "Link(s)"], ["E", "S", _a(bad), f"{_a(bad)}{_a(GOOD)}"])
    assert v.links == [GOOD]


@pytest.mark.parametrize("bad", BAD)
def test_source_column(bad):
    v = _version(["Era", "Name", "Notes", "Link(s)", "Sources"], ["E", "S", "n", "", f"{_a(bad)}{_a(GOOD)}"])
    assert [s.url for s in v.sources] == [GOOD]
    v = _version(["Era", "Name", "Notes", "Quality", "Source"], ["E", "S", "n", "CD", _a(bad)])
    assert v.links == []
    assert v.sources == []


@pytest.mark.parametrize("bad", BAD)
def test_misc_tab_links(bad):
    html = _table(["Era", "Name", "Notes", "Length", "Link(s)"], ["Era One", "Clip", "", "3:10", f"{_a(bad)}{_a(GOOD)}"])
    assert [e.links for e in parse_misc_tab(html, "music_videos", ["Era One"])] == [[GOOD]]


@pytest.mark.parametrize("bad", BAD)
def test_notice_links(bad):
    html = (
        f"<table><tr><td><a href='{bad}'>Please read this important notice first</a></td></tr></table>"
        + _table(["Era", "Name", "Notes", "Link(s)"], ["E", "S", "n", GOOD])
    )
    assert all(n.link is None or n.link.startswith("http") for n in parse_sheet(html, "Test").notices)


def test_unicode_case_folding_does_not_pass_as_http():
    assert _clean_link("httpſ://evil.test/x") == ""  # U+017F folds to "s" under re.I alone
    assert _split_links("httpſ://evil.test/x") == []


@pytest.mark.parametrize("url", ["http://", "https://", "https:///path", "https:// x"])
def test_hostless_links_are_dropped(url):
    assert _clean_link(url) == ""
