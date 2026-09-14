"""The parser regexes SonarQube flagged as super-linear (S8786), rewritten.

Each rewrite must give exactly what the old pattern gave, and finish in linear
time. The old patterns stay here as the oracle.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from src import parser

_OLD_STAR = re.compile(r"\s*([⭐★][\s⭐★☆]*)\s*$")
_OLD_STAR_GLYPH = re.compile(r"[⭐★]")
_OLD_COMPOUND = re.compile(r"\s*-\s*(~?)(HQ|LQ|CDQ)\b")
_OLD_PAIR = re.compile(r"\d+\s+[A-Za-z]")


def _old_split(text: str) -> tuple[str, str | None, int | None]:
    text = text.translate(parser._VARIATION_SELECTORS)
    rating = None
    m = _OLD_STAR.search(text)
    if m:
        rating = min(len(_OLD_STAR_GLYPH.findall(m.group(1))), 5)
        text = text[: m.start()].rstrip()
    quality = None
    qm = _OLD_COMPOUND.search(text)
    if qm:
        quality = parser._COMPOUND_QUALITY_NAMES[qm.group(2)]
        text = text[: qm.start()] + text[qm.end():]
        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"[ \t]+", " ", text.replace("\n", " ")).strip()
    return text, quality, rating


_ALPHABET = [" ", "\n", "\t", "⭐", "★", "☆", "️", "-", "~", "HQ", "LQ", "CDQ", "Full", "(", ")", "1", "23", "a"]


def _random_cells(n: int = 3000):
    rng = random.Random(20260914)
    for _ in range(n):
        yield "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 14)))


def test_compound_availability_split_matches_the_old_regexes():
    for cell in [
        "Full - HQ (Unofficial)\n⭐⭐⭐⭐☆", "Unconfirmed (Snippet - LQ)", "Full - ~CDQ",
        "☆ ⭐⭐", "a ☆ ⭐", "⭐️ ⭐️", "", "   ",
        *_random_cells(),
    ]:
        assert parser._split_compound_availability(cell) == _old_split(cell), repr(cell)


def test_stat_pair_count_matches_the_old_regex():
    for cell in ["1 OG File 45 Full", "12 3 a", "1a 2 b", *_random_cells()]:
        assert len(parser._STAT_PAIR_RE.findall(cell)) == len(_OLD_PAIR.findall(cell)), repr(cell)


@pytest.mark.parametrize("cell", [
    "⭐ " * 16_000 + "x",
    " " * 32_000 + "-" + " " * 32_000 + "x",
])
def test_availability_split_is_linear_on_hostile_cells(cell):
    start = time.perf_counter()
    parser._split_compound_availability(cell)
    assert time.perf_counter() - start < 0.5


def test_stat_pairs_are_linear_on_a_long_digit_run():
    start = time.perf_counter()
    parser._STAT_PAIR_RE.findall("1" * 64_000)
    assert time.perf_counter() - start < 0.5
