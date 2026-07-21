"""Shared fixtures for the LeakSheet test suite.

One place for the things every layer needs:

* **Cache isolation** — the file-based cache (``src.fetcher.CACHE_DIR``, re-bound
  in ``src.api``) is redirected to a per-test tmp dir so tests never read or
  write the real ``.cache/`` and never leak state into each other.
* **Mock sheets transport** — ``workbook_client`` builds a real
  ``httpx.AsyncClient`` backed by ``httpx.MockTransport`` that serves a synthetic
  multi-tab Google-Sheets workbook, and ``patch_sheets_client`` injects it into
  the production async fetch path (``src.fetcher._get_sheets_client``). This lets
  the *real* ``async_fetch_and_parse`` — tab discovery, prioritization, misc
  merge, art application — run end-to-end offline.
* **Synthetic fixtures** — ``read_synthetic`` loads the DMCA-safe HTML under
  ``tests/fixtures/synthetic/`` (invented artists, real tracker grammar).
* **TestClient** — ``api_client`` wraps the FastAPI app.

Nothing here hits the network; the ``live`` marker owns that.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

import httpx
import pytest

SYNTHETIC_DIR = Path(__file__).parent / "fixtures" / "synthetic"


# ---------------------------------------------------------------------------
# Cache isolation — never touch the real .cache/ during tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path_factory, monkeypatch):
    """Redirect the file cache to a tmp dir for every test.

    ``CACHE_DIR`` is a module global in ``src.fetcher`` and a re-exported name in
    ``src.api`` (image cache); both must point at the tmp dir so no test reads or
    writes the developer's real cache.

    The dir comes from ``tmp_path_factory`` (its own unique location), NOT the
    per-test ``tmp_path`` — tests that glob their own ``tmp_path`` for leftover
    files must not see this cache dir show up inside it.
    """
    import src.api as api
    import src.fetcher as fetcher

    cache_dir = tmp_path_factory.mktemp("leaksheet-cache")
    monkeypatch.setattr(fetcher, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(api, "CACHE_DIR", cache_dir)
    return cache_dir


@pytest.fixture(autouse=True)
def _fresh_shared_clients(monkeypatch):
    """Reset the module-global httpx clients before every test.

    pytest-asyncio runs each coroutine on a FRESH event loop, but the fetch /
    stream / proxy stacks cache module-global ``httpx.AsyncClient``s bound to
    whichever loop first created them (fine under uvicorn's single loop). Without
    a reset, an async test that touches the real client after an earlier test
    instantiated it dies with "RuntimeError: Event loop is closed". Applied
    suite-wide (not just ``-m live``) so an offline async test can't hit the same
    latent flake.
    """
    import src.api as api
    import src.fetcher as fetcher
    import src.streaming as streaming

    monkeypatch.setattr(fetcher, "_sheets_client", None)
    monkeypatch.setattr(streaming, "_shared_client", None)
    monkeypatch.setattr(api, "_proxy_client", None)


# ---------------------------------------------------------------------------
# Synthetic fixture loading
# ---------------------------------------------------------------------------

def read_synthetic(name: str) -> str:
    """Return the text of a synthetic fixture file (``.html`` suffix optional)."""
    if not name.endswith(".html"):
        name += ".html"
    return (SYNTHETIC_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def synthetic():
    """Callable that loads a synthetic fixture by name."""
    return read_synthetic


# ---------------------------------------------------------------------------
# Mock Google-Sheets transport — drives the real async fetch pipeline offline
# ---------------------------------------------------------------------------

def build_htmlview_base(tabs: dict[str, str], *, title: str = "Synth Tracker - Google Drive") -> str:
    """Build a Google-Sheets ``/htmlview`` base page for a {gid: tab_name} map.

    The real base page carries no ``<table>`` — only the JS ``items.push({...})``
    tab listing the fetcher scrapes for gids and tab names. Mirroring that shape
    is what makes ``_discover_gids`` / ``_discover_named_tabs`` /
    ``_prioritize_gids`` exercise their real code paths.
    """
    pushes = "\n".join(
        f'items.push({{name: "{_html.escape(name)}", '
        f'pageUrl: "/htmlview/sheet?headers=true&gid={gid}", gid: "{gid}"}});'
        for gid, name in tabs.items()
    )
    return (
        f"<html><head><title>{_html.escape(title)}</title></head><body>"
        f"<script>var items = [];\n{pushes}\n</script>"
        f"</body></html>"
    )


def make_workbook_handler(
    tab_html_by_gid: dict[str, str],
    *,
    base_html: str | None = None,
    tab_names: dict[str, str] | None = None,
    fail_gids: set[str] | None = None,
):
    """Return a ``httpx.MockTransport`` handler serving a synthetic workbook.

    * base page (request with no ``gid`` query) → ``base_html`` (auto-built from
      ``tab_names`` when not supplied), which contains the tab-listing JS.
    * ``…/htmlview/sheet?gid=N`` → the tab HTML for gid ``N`` (404 if unknown,
      503 if ``N`` is in ``fail_gids`` — for exercising fallback paths).
    """
    fail_gids = fail_gids or set()
    if base_html is None:
        names = tab_names or {gid: f"Tab {gid}" for gid in tab_html_by_gid}
        base_html = build_htmlview_base(names)

    def handler(request: httpx.Request) -> httpx.Response:
        gid = request.url.params.get("gid")
        if gid is None:
            return httpx.Response(200, html=base_html)
        if gid in fail_gids:
            return httpx.Response(503, text="upstream error")
        tab = tab_html_by_gid.get(gid)
        if tab is None:
            return httpx.Response(404, text="no such gid")
        return httpx.Response(200, html=tab)

    return httpx.MockTransport(handler)


@pytest.fixture
def workbook_client():
    """Factory → an ``httpx.AsyncClient`` backed by a synthetic workbook.

    Usage::

        client = workbook_client({"100": main_html, "200": misc_html},
                                 tab_names={"100": "Unreleased", "200": "Misc"})
    """
    created: list[httpx.AsyncClient] = []

    def _make(tab_html_by_gid, *, base_html=None, tab_names=None, fail_gids=None):
        transport = make_workbook_handler(
            tab_html_by_gid, base_html=base_html, tab_names=tab_names, fail_gids=fail_gids
        )
        client = httpx.AsyncClient(transport=transport, follow_redirects=True)
        created.append(client)
        return client

    yield _make
    # AsyncClient close is async; the event loop is gone by teardown, but the
    # MockTransport holds no sockets, so dropping the reference is sufficient.
    created.clear()


@pytest.fixture
def patch_sheets_client(monkeypatch):
    """Return an installer that makes ``async_fetch_and_parse`` use ``client``."""
    import src.fetcher as fetcher

    def _install(client: httpx.AsyncClient):
        monkeypatch.setattr(fetcher, "_get_sheets_client", lambda: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client():
    """A ``TestClient`` for the FastAPI app (context-managed for lifespan)."""
    from fastapi.testclient import TestClient

    from src.api import app

    with TestClient(app) as client:
        yield client
