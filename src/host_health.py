"""LeakSheet — per-provider stream health, shared by every worker through one file.

A provider that is down made every play attempt wait out a connect timeout. Known to
be down, /stream answers at once, and a prober notices recovery:
see docs/decisions.md::host_health.py.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import httpx

from src import fetcher
from src.streaming import UpstreamStatusError, resolve_stream_url, stream_audio

logger = logging.getLogger(__name__)

# Provider key (the iOS StreamResolver.Target names) -> the host users know it by.
PROVIDERS = {
    "pillows": "pillows.su",
    "imgur": "imgur.gg",
    "froste": "music.froste.lol",
    "kraken": "krakenfiles.com",
    "pixeldrain": "pixeldrain.com",
    "gdrive": "drive.google.com",
}
# Host of the URL resolve_stream_url emits -> provider.
_RESOLVED_HOSTS = {
    "api.pillows.su": "pillows",
    "imgur.gg": "imgur",
    "temp.imgur.gg": "imgur",
    "music.froste.lol": "froste",
    "krakenfiles.com": "kraken",
    "pixeldrain.com": "pixeldrain",
    "drive.google.com": "gdrive",
}

# One bad file must not take a provider down: soft failures (5xx, read timeouts)
# count only when several links fail within the window.
_SOFT_WINDOW_S = 120.0
_SOFT_FAILURES = 3
_SOFT_DISTINCT_LINKS = 2
PROBE_INTERVAL_S = 60.0
_PROBE_TIMEOUT_S = 15.0

# (path, inode, mtime_ns, state): a re-read only when another worker wrote the file.
# Every write is an os.replace, so the inode changes even within one mtime tick.
_cache: tuple[str, int, int, dict] | None = None


def provider_for(link: str) -> str | None:
    """The provider a tracker link streams from, or None for an unsupported link."""
    resolved = resolve_stream_url(link)
    return provider_of(resolved) if resolved else None


def provider_of(stream_url: str) -> str | None:
    """The provider of a URL resolve_stream_url emitted."""
    return _RESOLVED_HOSTS.get(urlparse(stream_url).hostname or "")


def _path():
    return fetcher.CACHE_DIR / "host_health.json"


def _read() -> dict:
    global _cache
    path = _path()
    try:
        st = path.stat()
    except OSError:
        return {}
    if _cache is not None and _cache[:3] == (str(path), st.st_ino, st.st_mtime_ns):
        return _cache[3]
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    _cache = (str(path), st.st_ino, st.st_mtime_ns, state)
    return state


@contextmanager
def _locked_state():
    """Read-modify-write under a flock shared by every worker."""
    global _cache
    fetcher.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(fetcher.CACHE_DIR / "host_health.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _cache = None
        state = _read()
        yield state
        fetcher._atomic_write_bytes(_path(), json.dumps(state).encode())
        st = _path().stat()
        _cache = (str(_path()), st.st_ino, st.st_mtime_ns, state)


def down(provider: str) -> dict | None:
    """The provider's entry when it is down, else None."""
    entry = _read().get(provider)
    return {**entry, "host": PROVIDERS[provider]} if entry and entry.get("status") == "down" else None


def record_success(provider: str) -> None:
    entry = _read().get(provider)
    if not entry or (entry.get("status") != "down" and not entry.get("failures")):
        return  # already up: no write on the hot path
    with _locked_state() as state:
        state[provider] = {"status": "up", "since": time.time(), "checked": time.time()}
    logger.info("stream host %s is up", PROVIDERS[provider])


def record_failure(provider: str, link: str, *, hard: bool, error: str) -> None:
    """Note a failed upstream request; *hard* (no connection at all) is down at once."""
    now = time.time()
    with _locked_state() as state:
        entry = state.setdefault(provider, {"status": "up", "since": now})
        entry["checked"] = now
        if entry["status"] == "down":
            return
        failures = [f for f in entry.get("failures", []) if now - f[0] <= _SOFT_WINDOW_S]
        failures.append([now, link])
        entry["failures"] = failures
        if hard or (
            len(failures) >= _SOFT_FAILURES
            and len({f[1] for f in failures}) >= _SOFT_DISTINCT_LINKS
        ):
            # Every distinct failing link is a probe candidate: one broken file must
            # not keep a recovered host down.
            links = list(dict.fromkeys(f[1] for f in reversed(failures)))[:_SOFT_DISTINCT_LINKS + 1]
            state[provider] = {
                "status": "down", "since": now, "checked": now, "probe": links, "error": error,
            }
            logger.warning("stream host %s is down: %s", PROVIDERS[provider], error)


def snapshot() -> list[dict]:
    """Every provider's status, for GET /hosts."""
    state = _read()
    out = []
    for provider, host in PROVIDERS.items():
        entry = state.get(provider, {})
        out.append({
            "provider": provider,
            "host": host,
            "status": entry.get("status", "up"),
            "since": entry.get("since"),
            "checked": entry.get("checked"),
        })
    return out


async def _answers(link: str) -> bool:
    """True when the provider serves *link*, or answers that the file is gone."""
    stream_url = resolve_stream_url(link)
    if not stream_url:
        return False
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_S):
            resp = await stream_audio(stream_url, range_header="bytes=0-0")
        if hasattr(resp, "aclose"):
            await resp.aclose()
        return True
    except UpstreamStatusError as e:
        return e.status_code < 500  # a missing or forbidden file is not an outage
    except (httpx.HTTPError, ValueError, TimeoutError, OSError) as e:
        logger.debug("stream host probe of %s failed: %r", link[:80], e)
        return False


async def _probe(provider: str, links: list[str]) -> None:
    for link in links:
        if await _answers(link):
            await asyncio.to_thread(record_success, provider)
            return
    await asyncio.to_thread(_touch_checked, provider)


def _touch_checked(provider: str) -> None:
    with _locked_state() as state:
        state.get(provider, {})["checked"] = time.time()


async def probe_once() -> None:
    """Re-probe every down provider, in the one worker holding the probe lock."""
    fetcher.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(fetcher.CACHE_DIR / "host_health.probe.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # another worker probes this round
        targets = [(p, e.get("probe") or []) for p, e in _read().items() if e.get("status") == "down"]
        await asyncio.gather(*(_probe(p, links) for p, links in targets if links))


async def probe_forever() -> None:
    """The lifespan task: probe down providers every PROBE_INTERVAL_S."""
    while True:
        await asyncio.sleep(PROBE_INTERVAL_S)
        try:
            await probe_once()
        except Exception as e:  # a probe round must never kill the loop
            logger.warning("stream host probe failed: %r", e)
