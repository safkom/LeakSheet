"""Live-layer fixtures.

The shared-httpx-client reset that live tests need (module-global
``httpx.AsyncClient``s are bound to the loop that created them, and
pytest-asyncio uses a fresh loop per test) now lives in the top-level
``tests/conftest.py`` (``_fresh_shared_clients``, autouse suite-wide), so there
is nothing live-specific to add here.
"""

from __future__ import annotations
