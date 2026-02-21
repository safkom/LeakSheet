"""
LeakSheet API – main FastAPI application.

Endpoints:
  GET /parse?url=<google_sheets_url>   – fetch and parse a public spreadsheet
  GET /parse/{spreadsheet_id}          – fetch and parse by spreadsheet ID
"""

import httpx
from fastapi import FastAPI, HTTPException, Query

from app.models import SpreadsheetResult
from app.parser import build_html_url, extract_spreadsheet_id, parse_html

app = FastAPI(
    title="LeakSheet API",
    description=(
        "Parse public Google Spreadsheets containing leaked music information. "
        "Returns structured data with artists (sheets), album eras, and song entries."
    ),
    version="1.0.0",
)

# HTTP client configuration
_TIMEOUT = 20.0  # seconds
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LeakSheetBot/1.0; "
        "+https://github.com/safkom/LeakSheet)"
    )
}


async def _fetch_html(url: str) -> str:
    """Fetch the HTML content of a URL, raising HTTPException on failure."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Failed to fetch spreadsheet: {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Network error while fetching spreadsheet: {exc}",
            ) from exc
    return response.text


@app.get("/parse", response_model=SpreadsheetResult, summary="Parse by URL")
async def parse_by_url(
    url: str = Query(
        ...,
        description="Full URL of a public Google Spreadsheet (e.g. https://docs.google.com/spreadsheets/d/ID/htmlview)",
        examples=["https://docs.google.com/spreadsheets/d/1hcRr6GIUNCV4z0iSXGxmLYrESkHfRxx6l5nk8d_Nsaw/htmlview"],
    )
) -> SpreadsheetResult:
    """
    Fetch and parse a public Google Spreadsheet from its URL.

    The spreadsheet must be publicly accessible (anyone with link can view).
    """
    spreadsheet_id = extract_spreadsheet_id(url)
    if not spreadsheet_id:
        raise HTTPException(
            status_code=400,
            detail="Could not extract a spreadsheet ID from the provided URL.",
        )

    html_url = build_html_url(spreadsheet_id)
    html = await _fetch_html(html_url)
    return parse_html(html, spreadsheet_id=spreadsheet_id, url=html_url)


@app.get(
    "/parse/{spreadsheet_id}",
    response_model=SpreadsheetResult,
    summary="Parse by spreadsheet ID",
)
async def parse_by_id(spreadsheet_id: str) -> SpreadsheetResult:
    """
    Fetch and parse a public Google Spreadsheet by its ID.

    The ID is the long alphanumeric string found in the spreadsheet URL between
    ``/d/`` and ``/edit`` (or ``/htmlview``).
    """
    html_url = build_html_url(spreadsheet_id)
    html = await _fetch_html(html_url)
    return parse_html(html, spreadsheet_id=spreadsheet_id, url=html_url)
