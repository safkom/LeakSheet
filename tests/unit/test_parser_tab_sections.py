"""Parser gaps found by diffing against yetracker.cc (2026-09-23)."""
from src.models import parse_song_credits
from src.parser import parse_misc_tab, parse_sheet


def _table(rows: list[list[str]]) -> str:
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table>{body}</table>"


STEMS = _table([
    ["Era", "Name", "Notes", "File Date", "Leak Date", "Full Length", "BPM", "Available Length", "Quality"],
    ["", "Alpha Era<br>(Aka)", "(01/01/2001) (Born)", "", "", "A paragraph describing the era", "", "", ""],
    ["", "Instrumentals", "", "", "", "", "", "", ""],
    ["Alpha Era", "Beat 1", "demo", "", "May 22, 2016", "1:44", "84", "Full", "High Quality"],
    ["", "Acapellas", "", "", "", "", "", "", ""],
    ["Alpha Era", "Song A", "vocals", "", "Apr 4, 2011", "2:01", "90", "Full", "High Quality"],
    ["", "Beta Era", "(02/02/2002) (Moved)", "", "", "Another paragraph", "", "", ""],
    ["Beta Era", "Beat 2", "demo", "", "Apr 4, 2011", "1:29", "101", "Full", "High Quality"],
])


def test_content_tab_label_rows_name_the_rows_below_them():
    entries = parse_misc_tab(STEMS, "stems", ["Alpha Era", "Beta Era"])
    assert [(e.era_name, e.section, e.name) for e in entries] == [
        ("Alpha Era", "Instrumentals", "Beat 1"),
        ("Alpha Era", "Acapellas", "Song A"),
        ("Beta Era", "", "Beat 2"),  # a new era starts with no section
    ]


def test_full_length_maps_to_length_but_an_era_paragraph_does_not():
    entries = parse_misc_tab(STEMS, "stems", ["Alpha Era", "Beta Era"])
    assert [e.length for e in entries] == ["1:44", "2:01", "1:29"]


MAIN = _table([
    ["Era", "Name", "Notes", "Track Length", "Leak Date", "Available Length", "Quality", "Link(s)"],
    ["3 OG File(s)\n1 Full", "Main Era", "(01/01/2001) (Start)", "", "", "", "", ""],
    ["Main Era", "Song One", "first", "3:00", "Jan 1, 2020", "Full", "CD Quality", ""],
    ["", "Late Sessions", "(05/05/2005) (Sessions begin)", "", "", "", "", ""],
    ["Main Era", "Song Two", "second", "2:00", "Jan 2, 2020", "Full", "CD Quality", ""],
    ["x", "Tour Recording", "(06/06/2006) (Live show)", "", "", "", "", ""],
    ["Main Era", "Song Three", "third", "1:00", "Jan 3, 2020", "Full", "CD Quality", ""],
])


def test_a_sub_era_label_keeps_its_timeline_and_a_one_char_typo_is_no_era():
    artist = parse_sheet(MAIN, "Test")
    assert [e.name for e in artist.eras] == ["Main Era"]
    sections = {s.name: s.notes for s in artist.eras[0].sections}
    assert sections["Late Sessions"] == "(05/05/2005) (Sessions begin)"
    assert sections["Tour Recording"] == "(06/06/2006) (Live show)"


def test_a_repeated_credit_name_is_listed_once():
    credits = parse_song_credits("Devil Weak\n(prod. Boogz) (prod. Boogz, Wallis Lane & Wheezy)")
    assert credits.producers == "Boogz, Wallis Lane & Wheezy"
    assert parse_song_credits("X\n(prod. A) (prod. B)").producers == "A, B"


def test_a_stray_closing_bracket_is_not_an_alt_title():
    assert parse_song_credits("Pablo\n(feat. Future) (prod. A & B))").alt_titles == []
