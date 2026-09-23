"""Every module-level regex in src/ stays linear on hostile 32 KB input.

Spreadsheet cells, page titles and tab names are attacker-controlled and
uncapped, so one super-linear pattern is a CPU denial of service. This walks
all compiled patterns instead of pinning them one at a time, so a new
quadratic pattern fails here the day it is added.
"""
import importlib
import re
import time

import pytest

MODULES = ["src.config", "src.models", "src.parser", "src.fetcher", "src.streaming", "src.api"]
UNITS = [
    "1", "1 ", " ", "\n", "a\n", "(", "((", "[", "a ", "a,", "&", "-", "/", " /",
    "feat. ", "prod. ", "down ", "fix ", "Samples a's 'x ", '{name:"',
]
SIZE = 32 * 1024
BUDGET_S = 0.1

# Used only with .match() at a known position, never .search(): timing them
# with .search would measure a call the code never makes.
ANCHORED = {"_OG_QUOTED_NAME_PATTERN", "_SAMPLE_POSSESSIVE_PATTERN", "BADGE_EMOJI_PATTERN"}


def _patterns():
    for mod_name in MODULES:
        mod = importlib.import_module(mod_name)
        for name, value in vars(mod).items():
            items = value if isinstance(value, (list, tuple)) else [value]
            for item in items:
                for pat in (item if isinstance(item, tuple) else (item,)):
                    if isinstance(pat, re.Pattern):
                        yield pytest.param(name, pat, id=f"{mod_name}.{name}")


@pytest.mark.parametrize("name,pattern", list(_patterns()))
def test_pattern_is_linear(name, pattern):
    run = pattern.match if name in ANCHORED else pattern.search
    for unit in UNITS:
        text = (unit * (SIZE // len(unit) + 1))[:SIZE]
        for probe in (text, "a" + text + "!"):
            start = time.perf_counter()
            run(probe)
            elapsed = time.perf_counter() - start
            assert elapsed < BUDGET_S, f"{name} took {elapsed:.2f}s on {unit!r} x {SIZE}"


def _hot_calls():
    from src import fetcher, models

    return [
        ("extract_samples", models.extract_samples, "Samples a's 'x " * 2200),
        ("extract_samples_quoted", models.extract_samples, 'Samples "a" by b, ' * 1800),
        ("parse_song_credits", models.parse_song_credits, "(" * SIZE),
        ("clean_sample_artist", models._clean_sample_artist, "x" + " " * SIZE + "y"),
        ("parse_era_stats", models.parse_era_stats, "1" * SIZE),
        ("infer_artist_name", fetcher._infer_artist_name, "a" + " " * SIZE + "x"),
        ("clean_tab_name", fetcher._clean_tab_name, "a" + " " * SIZE + "x"),
    ]


@pytest.mark.parametrize("label,func,arg", [pytest.param(*c, id=c[0]) for c in _hot_calls()])
def test_hot_function_is_linear(label, func, arg):
    start = time.perf_counter()
    func(arg)
    assert time.perf_counter() - start < 2 * BUDGET_S, label
