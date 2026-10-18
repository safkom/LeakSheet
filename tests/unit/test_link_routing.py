"""Which URLs on a song row are listen links and which are evidence.

Two shapes put playable-looking URLs in the wrong place: a tracker whose only link
column is headed "Source", and a row whose audio does not exist (rumoured, confirmed,
not available) but links a screenshot or article on a file host.
"""
from src.parser import parse_sheet

PILLOWS = "https://pillows.su/f/0123456789abcdef0123456789abcdef"
IMGUR = "https://imgur.gg/f/AbCdEf1"
ARTICLE = "https://news.example.test/story"


def _version(header: list[str], row: list[str]):
    cells = lambda r: "".join(f"<td>{c}</td>" for c in r)  # noqa: E731
    html = f"<table><tr>{cells(header)}</tr><tr>{cells(row)}</tr></table>"
    return parse_sheet(html, "Test").eras[0].songs[0].versions[0]


def _a(url: str) -> str:
    return f"<a href='{url}'>{url}</a>"


class TestSourceColumnHoldingListenLinks:
    HEADER = ["Era", "Name", "Notes", "Quality", "Source"]

    def test_stream_host_urls_become_links_when_no_link_column_exists(self):
        v = _version(self.HEADER, ["Era One", "Song One", "n", "CD Quality", f"{_a(PILLOWS)}<br>{_a(ARTICLE)}"])
        assert v.links == [PILLOWS]
        assert [s.url for s in v.sources] == [ARTICLE]

    def test_a_dedicated_link_column_keeps_sources_as_evidence(self):
        header = ["Era", "Name", "Notes", "Quality", "Link(s)", "Sources"]
        v = _version(header, ["Era One", "Song One", "n", "CD Quality", "", _a(PILLOWS)])
        assert v.links == []
        assert [s.url for s in v.sources] == [PILLOWS]


class TestRowsWithoutAudioLinkOnlyEvidence:
    HEADER = ["Era", "Name", "Notes", "Available Length", "Quality", "Link(s)"]

    def test_a_rumoured_row_moves_its_links_to_sources(self):
        v = _version(self.HEADER, ["Era One", "Song One", "n", "Rumored", "Not Available", _a(IMGUR)])
        assert v.links == []
        assert [s.url for s in v.sources] == [IMGUR]

    def test_not_available_quality_alone_is_enough(self):
        v = _version(self.HEADER, ["Era One", "Song One", "n", "", "Not Available", _a(PILLOWS)])
        assert v.links == []
        assert [s.url for s in v.sources] == [PILLOWS]

    def test_a_confirmed_row_moves_its_links_to_sources(self):
        v = _version(self.HEADER, ["Era One", "Song One", "n", "Confirmed", "", _a(ARTICLE)])
        assert v.links == []
        assert [s.url for s in v.sources] == [ARTICLE]

    def test_a_leaked_row_keeps_its_links(self):
        v = _version(self.HEADER, ["Era One", "Song One", "n", "Snippet", "Low Quality", _a(PILLOWS)])
        assert v.links == [PILLOWS]
        assert v.sources == []


def test_russian_headers_map_to_their_fields():
    header = ["Эра", "Название", "Примечания", "Длина", "Дата Cлива", "Категория",
              "Доступная длина", "Качество", "Ссылка"]
    v = _version(header, ["Era One", "Song One", "n", "2:00", "Jan 1, 2024", "Leak",
                          "Snippet", "High Quality", _a(PILLOWS)])
    assert (v.links, v.track_length, v.leak_date, v.type, v.available_length, v.quality) == (
        [PILLOWS], "2:00", "Jan 1, 2024", "Leak", "Snippet", "High Quality")


def test_spanish_headers_map_to_their_fields():
    header = ["Era", "Nombre", "Notas", "Tipo", "Disponible?", "Calidad", "Enlace"]
    v = _version(header, ["Era One", "Song One", "n", "Leak", "Snippet", "High Quality", _a(PILLOWS)])
    assert (v.name, v.type, v.available_length, v.quality, v.links) == (
        "Song One", "Leak", "Snippet", "High Quality", [PILLOWS])
