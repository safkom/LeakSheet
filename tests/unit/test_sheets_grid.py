"""extract_grid: a Sheets API v4 sheet becomes the rows extract_table gives for its htmlview.

Each rule here was found by diffing both sources cell by cell on real workbooks
(docs/decisions.md::parser.py::extract_grid). The fixtures are invented.
"""

from __future__ import annotations

from src.parser import _clean_link, extract_grid, extract_table, parse_misc_tab


def _sheet(rows, *, cols=3, frozen=0, merges=(), hidden_rows=(), hidden_cols=(), row_count=None):
    grid = {"rowCount": row_count if row_count is not None else len(rows), "columnCount": cols}
    if frozen:
        grid["frozenRowCount"] = frozen
    n = grid["rowCount"]
    return {
        "properties": {"sheetId": 7, "title": "Misc", "gridProperties": grid},
        "merges": [
            {"startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}
            for r0, r1, c0, c1 in merges
        ],
        "data": [{
            "rowData": [{"values": [c if isinstance(c, dict) else {"formattedValue": c} for c in r]} for r in rows],
            "rowMetadata": [{"hiddenByUser": True} if i in hidden_rows else {} for i in range(n)],
            "columnMetadata": [{"hiddenByFilter": True} if i in hidden_cols else {} for i in range(cols)],
        }],
    }


def _texts(rows):
    return [[c.text for c in r] for r in rows]


def _links(cell):
    return [_clean_link(link) for link in cell.links]


class TestShape:
    def test_rows_are_padded_to_the_grid(self):
        rows = extract_grid(_sheet([["a"], ["b", "c"]], cols=3, row_count=3))
        assert _texts(rows) == [["a", "", ""], ["b", "c", ""], ["", "", ""]]

    def test_an_empty_row_inside_the_data_is_kept(self):
        sheet = _sheet([["a"], [], ["b"]], cols=1)
        sheet["data"][0]["rowData"][1] = {}
        assert _texts(extract_grid(sheet)) == [["a"], [""], ["b"]]

    def test_frozen_rows_are_followed_by_an_empty_freezebar_row(self):
        rows = extract_grid(_sheet([["Era", "Name"], ["e1", "s1"]], cols=2, frozen=1))
        assert _texts(rows) == [["Era", "Name"], ["", ""], ["e1", "s1"]]

    def test_hidden_rows_and_columns_are_skipped(self):
        rows = extract_grid(_sheet([["a", "x", "b"], ["c", "y", "d"]], hidden_rows={1}, hidden_cols={1}))
        assert _texts(rows) == [["a", "b"]]

    def test_colspan_cells_stay_as_empty_cells(self):
        rows = extract_grid(_sheet([["wide", "", "z"]], merges=[(0, 1, 0, 2)]))
        assert _texts(rows) == [["wide", "", "z"]]

    def test_rowspan_drops_the_covered_cells_of_later_rows(self):
        # htmlview omits the <td>s a rowspan covers, so later cells shift left.
        rows = extract_grid(_sheet([["tall", "a", "b"], ["", "c", "d"]], merges=[(0, 2, 0, 1)]))
        assert _texts(rows) == [["tall", "a", "b"], ["c", "d"]]

    def test_a_row_fully_covered_by_a_rowspan_disappears(self):
        rows = extract_grid(_sheet([["tall", "x"], ["", ""], ["n", "m"]], cols=2, merges=[(0, 2, 0, 2)]))
        assert _texts(rows) == [["tall", "x"], ["n", "m"]]


class TestText:
    def test_text_is_stripped(self):
        assert _texts(extract_grid(_sheet([[" Era "]], cols=1))) == [["Era"]]

    def test_carriage_returns_become_line_breaks(self):
        rows = extract_grid(_sheet([["a\r\nb\rc"]], cols=1))
        assert rows[0][0].text == "a\nb\nc"

    def test_control_characters_become_replacement_characters(self):
        rows = extract_grid(_sheet([["Song \x9c and \x1fx\ttab"]], cols=1))
        assert rows[0][0].text == "Song \ufffd and \ufffdx\ttab"


class TestLinks:
    def test_whole_cell_hyperlink_spans_every_line(self):
        cell = {"formattedValue": "https://a.example/1\nLossless Needed", "hyperlink": "https://a.example/1",
                "textFormatRuns": [{"format": {"link": {"uri": "https://a.example/1"}}}, {"startIndex": 19, "format": {}}]}
        c = extract_grid(_sheet([[cell]], cols=1))[0][0]
        assert _links(c) == ["https://a.example/1"]
        assert c.link_lines == [1]

    def test_link_runs_give_one_link_each_with_the_line_it_ends_on(self):
        text = "one\ntwo\nthree"
        cell = {"formattedValue": text, "textFormatRuns": [
            {"format": {"link": {"uri": "https://a.example/1"}}},
            {"startIndex": 3, "format": {}},
            {"startIndex": 8, "format": {"link": {"uri": "https://a.example/3"}}},
        ]}
        c = extract_grid(_sheet([[cell]], cols=1))[0][0]
        assert _links(c) == ["https://a.example/1", "https://a.example/3"]
        assert c.link_lines == [0, 2]

    def test_run_offsets_count_utf16_units(self):
        # Each 🎵 is two UTF-16 units: the linked run ends at unit 4, before the line break.
        text = "🎵🎵\nafter"
        cell = {"formattedValue": text, "textFormatRuns": [
            {"format": {"link": {"uri": "https://a.example/x"}}}, {"startIndex": 4, "format": {}}]}
        c = extract_grid(_sheet([[cell]], cols=1))[0][0]
        assert _links(c) == ["https://a.example/x"]
        assert c.link_lines == [0]

    def test_smart_chip_links_are_links(self):
        cell = {"formattedValue": "see @", "chipRuns": [
            {"startIndex": 4, "chip": {"richLinkProperties": {"uri": "https://drive.example/f"}}}]}
        assert _links(extract_grid(_sheet([[cell]], cols=1))[0][0]) == ["https://drive.example/f"]

    def test_a_stored_google_redirect_link_unwraps_once_like_htmlview(self):
        stored = "https://www.google.com/url?q=https://a.example/x&sa=D"
        cell = {"formattedValue": stored, "hyperlink": stored}
        assert _links(extract_grid(_sheet([[cell]], cols=1))[0][0]) == [stored]


class TestParity:
    HTML = (
        "<table><tr><td>Era</td><td>Name</td><td>Link(s)</td></tr>"
        "<tr><td>Debut Era</td><td>Clip One</td>"
        '<td><a href="https://www.google.com/url?q=https://v.example/1&amp;sa=D">https://v.example/1</a></td></tr>'
        "</table>"
    )

    def test_misc_parse_from_grid_matches_htmlview(self):
        sheet = _sheet([
            ["Era", "Name", "Link(s)"],
            ["Debut Era", "Clip One", {"formattedValue": "https://v.example/1", "hyperlink": "https://v.example/1"}],
        ])
        grid_rows = extract_grid(sheet)
        html_rows = extract_table(self.HTML)
        assert _texts(grid_rows) == _texts(html_rows)
        assert [_links(c) for r in grid_rows for c in r] == [_links(c) for r in html_rows for c in r]
        from_grid = parse_misc_tab(grid_rows, "misc", [])
        from_html = parse_misc_tab(self.HTML, "misc", [])
        assert [e.model_dump() for e in from_grid] == [e.model_dump() for e in from_html]
        assert from_grid
