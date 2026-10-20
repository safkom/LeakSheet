from src.parser import _Cell, _parse_song_row


def test_credit_only_name_cell_keeps_a_title():
    v = _parse_song_row([_Cell(text="(prod. Someone)")], {"name": 0})
    assert v is not None and v.name


def test_alt_title_promoted_when_title_empty():
    v = _parse_song_row([_Cell(text="(feat. A)\n(Real Name)")], {"name": 0})
    assert v is not None and v.name == "Real Name"


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
