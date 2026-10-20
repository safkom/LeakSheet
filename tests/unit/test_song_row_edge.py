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
    footer = [[_Cell(text="Total Links 3"), _Cell(text="Total Full 2")]]
    assert _find_global_stats(footer) is not None
