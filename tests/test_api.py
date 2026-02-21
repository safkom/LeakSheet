"""Tests for the FastAPI endpoints."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_HTML = (FIXTURE_DIR / "sample_sheet.html").read_text(encoding="utf-8")

client = TestClient(app)


class TestParseByUrl:
    def test_valid_url_returns_200(self):
        with patch("app.main._fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
            response = client.get(
                "/parse",
                params={"url": "https://docs.google.com/spreadsheets/d/TEST_ID/htmlview"},
            )
        assert response.status_code == 200

    def test_response_contains_spreadsheet_id(self):
        with patch("app.main._fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
            response = client.get(
                "/parse",
                params={"url": "https://docs.google.com/spreadsheets/d/TEST_ID/htmlview"},
            )
        data = response.json()
        assert data["spreadsheet_id"] == "TEST_ID"

    def test_response_contains_sheets(self):
        with patch("app.main._fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
            response = client.get(
                "/parse",
                params={"url": "https://docs.google.com/spreadsheets/d/TEST_ID/htmlview"},
            )
        data = response.json()
        assert len(data["sheets"]) == 2

    def test_invalid_url_returns_400(self):
        response = client.get("/parse", params={"url": "https://example.com/not-a-sheet"})
        assert response.status_code == 400

    def test_missing_url_returns_422(self):
        response = client.get("/parse")
        assert response.status_code == 422


class TestParseById:
    def test_valid_id_returns_200(self):
        with patch("app.main._fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
            response = client.get("/parse/TEST_ID")
        assert response.status_code == 200

    def test_response_contains_spreadsheet_id(self):
        with patch("app.main._fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
            response = client.get("/parse/TEST_ID")
        data = response.json()
        assert data["spreadsheet_id"] == "TEST_ID"

    def test_response_sheets_and_eras(self):
        with patch("app.main._fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
            response = client.get("/parse/TEST_ID")
        data = response.json()
        drake = next(s for s in data["sheets"] if s["name"] == "Drake")
        assert len(drake["eras"]) == 2

    def test_response_songs(self):
        with patch("app.main._fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
            response = client.get("/parse/TEST_ID")
        data = response.json()
        drake = next(s for s in data["sheets"] if s["name"] == "Drake")
        tml = next(e for e in drake["eras"] if "Thank Me Later" in e["name"])
        song_names = [s["name"] for s in tml["songs"]]
        assert "Fear" in song_names
