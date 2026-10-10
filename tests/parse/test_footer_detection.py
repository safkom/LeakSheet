"""Footer keywords end the song list only when a cell OPENS with them.

Song notes mention the same words in prose ("leaked via the changelog drop",
"a beat idea for TrackerHub"); a substring match there flagged the row as
footer, and every later song in the era was dropped with it.
"""
import pytest

from src.parser import parse_sheet

HEADER = (
    "<tr><td>Era</td><td>Name</td><td>Notes</td><td>Track Length</td>"
    "<td>Available Length</td><td>Quality</td><td>Link(s)</td></tr>"
)
ERA = "<tr><td>3 OG File(s)<br>2 Full</td><td>Alpha Era</td><td>(2020) (started)</td></tr>"


def _song(name: str, notes: str = "plain", era: str = "Alpha Era") -> str:
    return (
        f"<tr><td>{era}</td><td>{name}</td><td>{notes}</td><td>3:00</td>"
        "<td>Full</td><td>High Quality</td>"
        '<td><a href="https://pillows.su/f/abc">link</a></td></tr>'
    )


def _songs(*rows: str) -> list[str]:
    artist = parse_sheet("<table>" + HEADER + ERA + "".join(rows) + "</table>", "X")
    return [s.base_name for e in artist.eras for sec in e.sections for s in sec.songs]


@pytest.mark.parametrize("notes", [
    "Leaked via the changelog drop.",
    "Was on other trackers before.",
    "Uploaded to a file hosting site.",
    "Listed under the Total Full count.",
    "Mentioned in progress reports.",
    "Got pulled, see the update notes.",
    "Made by users of TrackerHub.",
])
def test_keyword_in_song_notes_keeps_the_song_and_its_successors(notes):
    assert _songs(_song("A", notes), _song("B"), _song("C")) == ["A", "B", "C"]


def test_keyword_in_a_name_alias_line_keeps_the_song():
    assert _songs(_song("A<br>(Beat idea for TrackerHub)"), _song("B")) == ["A", "B"]


def test_keyword_on_an_era_less_row_keeps_the_song():
    assert _songs(_song("A"), _song("B", "found on other trackers", era=""), _song("C")) == [
        "A", "B", "C",
    ]


@pytest.mark.parametrize("footer", [
    "🔗 616 Total Links",
    "Changelogs",
    "Tracker Guidelines",
    "Want to contribute? Join the server",
    "Current Editors:<br>someone",
])
def test_real_footer_rows_still_end_the_song_list(footer):
    row = f"<tr><td>{footer}</td><td></td><td></td></tr>"
    assert _songs(_song("A"), row, _song("B")) == ["A"]
