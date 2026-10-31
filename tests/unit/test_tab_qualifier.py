"""A tab's trailing qualifier ranks a namesake tab: newer copy, plain, other, stale."""

import pytest

from src.fetcher import _is_newer_qualifier, _tab_qualifier_rank


@pytest.mark.parametrize("qualifier", ["(new)", "[NEW!]", "( latest )", "(v2)", "(v10)", "(2.0)", "[10.0]"])
def test_newer_marks(qualifier):
    assert _is_newer_qualifier(qualifier.lower())


@pytest.mark.parametrize("qualifier", ["(v1)", "(1.0)", "(v2.0)", "(2)", "(new leaks)", "(newer)", "(v)", "(v\u0662)", "(\uff12.0)"])
def test_not_newer_marks(qualifier):
    assert not _is_newer_qualifier(qualifier)


def test_rank_order():
    assert _tab_qualifier_rank("Unreleased [NEW]") == 0
    assert _tab_qualifier_rank("Unreleased") == 1
    assert _tab_qualifier_rank("Unreleased (WIP)") == 2
    assert _tab_qualifier_rank("Unreleased (Old)") == 3
