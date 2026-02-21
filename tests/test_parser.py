"""Tests for the spreadsheet HTML parser."""

from pathlib import Path

import pytest

from app.parser import (
    build_html_url,
    extract_spreadsheet_id,
    parse_html,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_HTML = (FIXTURE_DIR / "sample_sheet.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# extract_spreadsheet_id
# ---------------------------------------------------------------------------

class TestExtractSpreadsheetId:
    def test_full_url(self):
        url = "https://docs.google.com/spreadsheets/d/1hcRr6GIUNCV4z0iSXGxmLYrESkHfRxx6l5nk8d_Nsaw/htmlview"
        assert extract_spreadsheet_id(url) == "1hcRr6GIUNCV4z0iSXGxmLYrESkHfRxx6l5nk8d_Nsaw"

    def test_edit_url(self):
        url = "https://docs.google.com/spreadsheets/d/ABC123xyz/edit#gid=0"
        assert extract_spreadsheet_id(url) == "ABC123xyz"

    def test_invalid_url(self):
        assert extract_spreadsheet_id("https://example.com/not-a-sheet") is None

    def test_empty_string(self):
        assert extract_spreadsheet_id("") is None


# ---------------------------------------------------------------------------
# build_html_url
# ---------------------------------------------------------------------------

class TestBuildHtmlUrl:
    def test_builds_correct_url(self):
        result = build_html_url("MY_SHEET_ID")
        assert result == "https://docs.google.com/spreadsheets/d/MY_SHEET_ID/htmlview"


# ---------------------------------------------------------------------------
# parse_html – sheet discovery
# ---------------------------------------------------------------------------

class TestParseHtmlSheets:
    def setup_method(self):
        self.result = parse_html(SAMPLE_HTML, spreadsheet_id="test_id", url="http://test")

    def test_spreadsheet_id_preserved(self):
        assert self.result.spreadsheet_id == "test_id"

    def test_url_preserved(self):
        assert self.result.url == "http://test"

    def test_correct_number_of_sheets(self):
        assert len(self.result.sheets) == 2

    def test_sheet_names(self):
        names = [s.name for s in self.result.sheets]
        assert "Drake" in names
        assert "Kanye West" in names


# ---------------------------------------------------------------------------
# parse_html – eras
# ---------------------------------------------------------------------------

class TestParseHtmlEras:
    def setup_method(self):
        self.result = parse_html(SAMPLE_HTML, spreadsheet_id="test_id", url="http://test")
        self.drake = next(s for s in self.result.sheets if s.name == "Drake")
        self.kanye = next(s for s in self.result.sheets if s.name == "Kanye West")

    def test_drake_era_count(self):
        assert len(self.drake.eras) == 2

    def test_drake_era_names(self):
        era_names = [e.name for e in self.drake.eras]
        assert any("Thank Me Later" in n for n in era_names)
        assert any("Take Care" in n for n in era_names)

    def test_kanye_era_count(self):
        assert len(self.kanye.eras) == 1

    def test_kanye_era_name(self):
        assert "Late Registration" in self.kanye.eras[0].name


# ---------------------------------------------------------------------------
# parse_html – songs
# ---------------------------------------------------------------------------

class TestParseHtmlSongs:
    def setup_method(self):
        self.result = parse_html(SAMPLE_HTML, spreadsheet_id="test_id", url="http://test")
        self.drake = next(s for s in self.result.sheets if s.name == "Drake")
        self.kanye = next(s for s in self.result.sheets if s.name == "Kanye West")
        self.tml_era = next(e for e in self.drake.eras if "Thank Me Later" in e.name)
        self.tc_era = next(e for e in self.drake.eras if "Take Care" in e.name)
        self.lr_era = self.kanye.eras[0]

    def test_tml_song_count(self):
        assert len(self.tml_era.songs) == 3

    def test_tc_song_count(self):
        assert len(self.tc_era.songs) == 2

    def test_lr_song_count(self):
        assert len(self.lr_era.songs) == 2

    def test_song_name_parsed(self):
        names = [s.name for s in self.tml_era.songs]
        assert "Fear" in names
        assert "Closer" in names
        assert "Halfway Through The Night" in names

    def test_song_version_parsed(self):
        fear = next(s for s in self.tml_era.songs if s.name == "Fear")
        assert fear.version == "Demo"

    def test_song_features_parsed(self):
        closer = next(s for s in self.tml_era.songs if s.name == "Closer")
        assert closer.features == "Lil Wayne"

    def test_song_empty_features_is_none(self):
        fear = next(s for s in self.tml_era.songs if s.name == "Fear")
        # Empty cell → None
        assert fear.features is None

    def test_song_notes_parsed(self):
        fear = next(s for s in self.tml_era.songs if s.name == "Fear")
        assert fear.notes == "Unreleased"

    def test_song_length_parsed(self):
        fear = next(s for s in self.tml_era.songs if s.name == "Fear")
        assert fear.length == "3:42"

    def test_kanye_song_names(self):
        names = [s.name for s in self.lr_era.songs]
        assert "Gone" in names
        assert "Gold Digger" in names

    def test_kanye_song_features(self):
        gone = next(s for s in self.lr_era.songs if s.name == "Gone")
        assert gone.features == "Otis Redding"


# ---------------------------------------------------------------------------
# parse_html – edge cases
# ---------------------------------------------------------------------------

class TestParseHtmlEdgeCases:
    def test_empty_html(self):
        result = parse_html("<html><body></body></html>")
        assert result.sheets == []

    def test_no_eras(self):
        html = """
        <div id="sheet-menu"><ul>
          <li><a href="#gid=0">Artist</a></li>
        </ul></div>
        <div id="gid=0">
          <table class="waffle">
            <tbody>
              <tr><td>Song Name</td><td>Version</td></tr>
              <tr><td>My Song</td><td>Demo</td></tr>
            </tbody>
          </table>
        </div>
        """
        result = parse_html(html)
        assert len(result.sheets) == 1
        sheet = result.sheets[0]
        # Songs with no era header go into "Unknown Era"
        assert len(sheet.eras) == 1
        assert sheet.eras[0].name == "Unknown Era"
        assert sheet.eras[0].songs[0].name == "My Song"

    def test_blank_song_rows_skipped(self):
        html = """
        <div id="sheet-menu"><ul>
          <li><a href="#gid=0">Artist</a></li>
        </ul></div>
        <div id="gid=0">
          <table class="waffle">
            <tbody>
              <tr><td colspan="3">Some Era</td></tr>
              <tr><td>Real Song</td><td>V1</td><td></td></tr>
              <tr><td></td><td></td><td></td></tr>
              <tr><td>Another Song</td><td>V2</td><td></td></tr>
            </tbody>
          </table>
        </div>
        """
        result = parse_html(html)
        era = result.sheets[0].eras[0]
        assert len(era.songs) == 2
        assert era.songs[0].name == "Real Song"
        assert era.songs[1].name == "Another Song"
