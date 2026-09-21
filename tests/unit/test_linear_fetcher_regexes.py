"""Two fetcher.py regexes SonarQube flagged as super-linear (S8786), rewritten.

Each rewrite must give exactly what the old pattern gave, and finish in linear
time. The old patterns stay here as the oracle — same convention as
tests/unit/test_linear_parser_regexes.py.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from src.fetcher import _clean_tab_name, _infer_artist_name

_OLD_PAREN_STRIP = re.compile(r"\s*[\(\[][^)\]]*[\)\]]\s*$")
_NEW_PAREN_STRIP = re.compile(r"\s*[\(\[][^()\[\]]*[\)\]]\s*$")


def _old_clean_tab_name(name: str) -> str:
    from src.fetcher import _EMOJI_RE

    clean = _EMOJI_RE.sub(" ", name).strip().lower()
    clean = re.sub(r"[\(\[][^)\]]*[\)\]]\s*$", "", clean).strip()
    clean = re.sub(r"\s*/\s*", " / ", clean)
    return re.sub(r"\s+", " ", clean).strip()


_ALPHABET = [" ", "a", "Tracker", "-", "PUBLIC", "(x)", "[y]", "()", "[]"]


def _random_titles(n: int = 3000):
    # Whole bracket groups as atomic tokens, not raw '(' '[' chars in
    # isolation — real tab/tracker names never nest a stray '[' inside a
    # '(...)' group (or vice versa) the way arbitrary character fuzzing
    # would. That specific shape is exactly what the S8786 fix changes the
    # handling of (see the code comment) — it's not a realistic name to hold
    # as an oracle case, only a synthetic one the old pattern happened to
    # "match" by scanning straight through the embedded bracket.
    rng = random.Random(20260917)
    for _ in range(n):
        yield "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 10)))


def test_paren_strip_matches_the_old_pattern():
    for name in [
        "Drake Tracker (reup 12.29.25) - Google Drive",
        "Playboi Carti Tracker [Official]",
        "No brackets here",
        "Unclosed (paren",
        "Unclosed [bracket",
        "(((((",
        "[[[[[",
        "(a(a(a(a",
        *_random_titles(),
    ]:
        old = _OLD_PAREN_STRIP.search(name)
        new = _NEW_PAREN_STRIP.search(name)
        assert (old.span() if old else None) == (new.span() if new else None), repr(name)


def test_infer_artist_name_still_strips_trailing_parens():
    # Regression guard: the fix must not change real (non-nested) behavior.
    assert _infer_artist_name("Drake Tracker (reup 12.29.25) - Google Drive") == "Drake"
    assert _infer_artist_name("Playboi Carti Tracker [Official]") == "Playboi Carti"


# The oracle test above deliberately never generates a mismatched inner bracket
# — which is the ONE input shape where the S8786 rewrite and the old pattern
# disagree, so on its own it proves less than its name suggests. Pin the
# divergence explicitly, on the NEW expected output, so the behaviour change is
# a recorded decision rather than a gap. See
# docs/decisions.md::fetcher.py::paren-strip-s8786.
@pytest.mark.parametrize(
    ("name", "old_result", "new_result"),
    [
        ("Name (a [b)", "Name", "Name (a"),
        ("Name [a (b]", "Name", "Name [a"),
    ],
)
def test_mismatched_inner_brackets_strip_the_inner_group_now(name, old_result, new_result):
    assert _OLD_PAREN_STRIP.search(name)
    assert name[: _OLD_PAREN_STRIP.search(name).start()].strip() == old_result
    assert _infer_artist_name(name) == new_result


def test_clean_tab_name_matches_the_old_function():
    for name in [
        "🎵 Unreleased (WIP)",
        "Grails / Wanted",
        "Best Of [Official]",
        "No brackets",
        "(((((",
        *_random_titles(),
    ]:
        assert _clean_tab_name(name) == _old_clean_tab_name(name), repr(name)


@pytest.mark.parametrize(
    "hostile",
    [
        "(" * 16_000 + "x",
        "[" * 16_000 + "x",
        "(a" * 16_000,
    ],
)
def test_paren_strip_is_linear_on_hostile_names(hostile):
    start = time.perf_counter()
    _infer_artist_name(hostile)
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize(
    "hostile",
    [
        "(" * 16_000 + "x",
        "(a" * 16_000,
    ],
)
def test_clean_tab_name_is_linear_on_hostile_names(hostile):
    start = time.perf_counter()
    _clean_tab_name(hostile)
    assert time.perf_counter() - start < 0.5
