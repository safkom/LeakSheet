"""LeakSheet — Sheets API v4 reads of a docs.google.com workbook's content tabs.

One spreadsheets.get returns every requested tab's cells, which `extract_grid`
turns into the rows the htmlview parser reads. Off unless LEAKSHEET_GOOGLE_API_KEY
is set; every failure returns None so the caller falls back to htmlview.
See docs/decisions.md::sheets_api.py.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import time

import httpx

from src.config import USER_AGENT
from src.parser import _Cell, extract_grid

logger = logging.getLogger(__name__)

API_URL = "https://sheets.googleapis.com/v4/spreadsheets/"
# Only what the parser reads: colours and notes would multiply the payload.
_FIELDS = (
    "sheets(properties(sheetId,title,gridProperties),merges,"
    "data(rowMetadata(hiddenByUser,hiddenByFilter),columnMetadata(hiddenByUser,hiddenByFilter),"
    "rowData(values(formattedValue,hyperlink,dataValidation/condition/type,textFormatRuns(startIndex,format/link/uri),chipRuns))))"
)
# Decoded JSON costs ~7x its size in memory; a larger body falls back to htmlview.
MAX_BODY_BYTES = 16 * 1024 * 1024
# Whole-call deadline: a slow API must not delay every tab's htmlview fallback.
TIMEOUT_S = 15.0
_DEFAULT_BACKOFF_S = 60.0
_MAX_BACKOFF_S = 3600.0
# Per worker, like every process global here: each of the 3 workers backs off on its own 429.
_backoff_until = 0.0


def api_key() -> str:
    return os.environ.get("LEAKSHEET_GOOGLE_API_KEY", "").strip()


def _a1(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _retry_after(resp: httpx.Response) -> float:
    try:
        return min(_MAX_BACKOFF_S, max(1.0, float(resp.headers.get("Retry-After", ""))))
    except ValueError:
        return _DEFAULT_BACKOFF_S


def _quota_hit(resp: httpx.Response, body: bytes) -> bool:
    return resp.status_code == 429 or (resp.status_code == 403 and b"rateLimitExceeded" in body)


def _key_refused(resp: httpx.Response, body: bytes) -> bool:
    """The API turned the key itself away (disabled API, restriction, invalid key): pause it."""
    if resp.status_code != 200 and (b"SERVICE_DISABLED" in body or b"API_KEY_" in body):
        _pause(_DEFAULT_BACKOFF_S)
        logger.warning("Sheets API refused the key (%d); htmlview only for a while", resp.status_code)
        return True
    return False


def _pause(seconds: float) -> None:
    global _backoff_until
    _backoff_until = time.monotonic() + seconds


def _rows_by_gid(body: bytes, gids: set[str]) -> dict[str, list[list[_Cell]]]:
    rows: dict[str, list[list[_Cell]]] = {}
    for sheet in json.loads(body).get("sheets") or []:
        gid = str((sheet.get("properties") or {}).get("sheetId"))
        if gid in gids:
            try:
                rows[gid] = extract_grid(sheet)
            except ValueError as e:  # this tab alone falls back to htmlview
                logger.warning("Sheets API tab %s skipped: %s", gid, e)
    return rows


async def _get(
    client: httpx.AsyncClient, sheet_id: str, key: str, params: list, *, timeout: float, max_bytes: int,
) -> tuple[httpx.Response, bytearray] | None:
    request = client.build_request(
        "GET", API_URL + sheet_id, params=params, timeout=timeout,
        # Google APIs compress only for a User-Agent containing "gzip".
        headers={"X-Goog-Api-Key": key, "User-Agent": f"{USER_AGENT} (gzip)", "Accept-Encoding": "gzip"},
    )
    try:
        # Never follow a redirect: the key header would go with it.
        resp = await client.send(request, stream=True, follow_redirects=False)
        try:
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    logger.warning("Sheets API body for %s over %d bytes", sheet_id, max_bytes)
                    return None
        finally:
            await resp.aclose()
    except httpx.HTTPError as e:
        logger.warning("Sheets API request for %s failed: %s", sheet_id, type(e).__name__)
        return None
    return resp, body


async def fetch_tabs(
    client: httpx.AsyncClient,
    sheet_id: str,
    tabs: dict[str, str],
    *,
    timeout: float,
    max_bytes: int,
) -> dict[str, list[list[_Cell]]] | None:
    """{gid: rows} for the tabs named in *tabs* ({gid: title}); None when the API is off or fails.

    A tab missing from the result is the caller's to read from htmlview.
    """
    key = api_key()
    if not key or not tabs or time.monotonic() < _backoff_until:
        return None
    get = functools.partial(_get, client, sheet_id, key, timeout=timeout, max_bytes=max_bytes)

    async def request() -> tuple[httpx.Response, bytes] | None:
        titles = tabs
        for attempt in range(2):
            params = [("includeGridData", "true"), ("fields", _FIELDS)]
            got = await get(params + [("ranges", _a1(title)) for title in titles.values()])
            if got is None:
                return None
            resp, body = got
            if _key_refused(resp, body):
                return None
            if resp.status_code != 400 or attempt:
                return resp, body
            # The htmlview tab listing trims names; ask for the exact titles by sheet id.
            got = await get([("fields", "sheets.properties(sheetId,title)")])
            if got is None:
                return None
            if got[0].status_code != 200:
                # Without a pause, a key this lookup cannot pass costs two calls on every parse.
                _pause(_retry_after(got[0]) if _quota_hit(*got) else _DEFAULT_BACKOFF_S)
                return None
            try:
                exact = {str(p.get("sheetId")): p.get("title") for p in
                         (sh.get("properties") or {} for sh in json.loads(got[1]).get("sheets") or [])}
            except (ValueError, AttributeError) as e:
                logger.warning("Sheets API titles for %s unreadable: %s", sheet_id, e)
                return None
            titles = {gid: exact[gid] for gid in tabs if exact.get(gid)}
            if not titles:
                return None
        return None

    try:
        async with asyncio.timeout(min(timeout, TIMEOUT_S)):
            got = await request()
    except TimeoutError:
        logger.warning("Sheets API for %s timed out; reading htmlview", sheet_id)
        return None
    if got is None:
        return None
    resp, body = got
    if _quota_hit(resp, body):
        _pause(_retry_after(resp))
        logger.warning("Sheets API quota hit (%d); htmlview only for a while", resp.status_code)
        return None
    if resp.status_code != 200:
        logger.warning("Sheets API answered %d for %s", resp.status_code, sheet_id)
        return None
    try:
        return await asyncio.to_thread(_rows_by_gid, body, set(tabs))
    except (ValueError, AttributeError, TypeError) as e:
        logger.warning("Sheets API body for %s unreadable: %s", sheet_id, e)
        return None
