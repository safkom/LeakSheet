from src.models import Badge
from src.parser import _Cell, _parse_song_row


def test_credit_only_name_cell_keeps_a_title():
    v = _parse_song_row([_Cell(text="(prod. Someone)")], {"name": 0})
    assert v is not None
    assert v.name


def test_alt_title_promoted_when_title_empty():
    v = _parse_song_row([_Cell(text="(feat. A)\n(Real Name)")], {"name": 0})
    assert v is not None
    assert v.name == "Real Name"


def test_global_stats_needs_two_stat_cells():
    from src.parser import _find_global_stats

    note = [[_Cell(text="Note: Total Full count excludes snippets")]]
    assert _find_global_stats(note) is None
    footer = [[_Cell(text="10 Total Links\n2 Missing Links"), _Cell(text="5 Lossless"), _Cell(text="7 Total Full")]]
    assert _find_global_stats(footer) is not None
    one_cell = [[_Cell(text="3 Total Links\n2 Lossless\n4 Total Full")]]
    assert _find_global_stats(one_cell) is not None


def test_confirmed_only_stats_cell_is_an_era_header():
    from src.parser import _is_era_header

    row = [_Cell(text="1 Confirmed"), _Cell(images=["https://x.test/a.png"]), _Cell(text="(2009) (Era)")]
    assert _is_era_header(row)


def test_artistgrid_csv_quoted_newline_and_u2028_and_full_url():
    from src.parser import parse_artistgrid_csv

    text = (
        'name,url,credit,links_work,updated,best\n'
        '"A\nB",abc123,x,,,\n'
        'C D,https://tracker.example.com/,,,,\n'
    )
    entries = {e.name: e.url for e in parse_artistgrid_csv(text)}
    assert entries["A\nB"] == "https://docs.google.com/spreadsheets/d/abc123/edit"
    assert entries["C D"] == "https://tracker.example.com/"


def test_ai_flagged_version_groups_with_its_song_and_keeps_its_badge():
    import tests.parse.test_wire_contract as wire
    from src.parser import parse_sheet

    def row(name):
        # Song row shape the wire fixture uses: era, name, notes, length, date, availability.
        return ["Synth Era", name, "", "3:00", "Jan 1, 2020", "Full (HQ)", "", "", ""]

    era = ["2 OG File(s)\n2 Full", "Synth Era", "(01/01/2001) (Start)", "", "", "", "", "", ""]
    table = wire._table([wire._HEADER, era, row("⭐🤖 Song [V2]"), row("Song [V1]")])
    artist = parse_sheet(table, "Synth")
    songs = [s for e in artist.eras for sec in e.sections for s in sec.songs]
    assert len(songs) == 1
    by_tag = {v.version_tag: v for v in songs[0].versions}
    assert by_tag["V2"].badge == Badge.AI
    assert by_tag["V1"].badge is None
    assert songs[0].badge == Badge.AI
