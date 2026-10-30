"""The scripts/tools helpers import cleanly and do nothing at import: conftest refuses the network."""

import importlib
import pathlib

import pytest

TOOLS = sorted(p.stem for p in pathlib.Path("scripts/tools").glob("*.py"))


@pytest.mark.parametrize("name", TOOLS)
def test_tool_imports_without_side_effects(name):
    importlib.import_module(f"scripts.tools.{name}")
