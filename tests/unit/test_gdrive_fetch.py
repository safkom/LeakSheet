"""_fetch_gdrive: every redirect hop is vetted, and only a 200 can be an interstitial."""

from __future__ import annotations

import httpx
import pytest

from src import streaming

URL = "https://drive.google.com/uc?export=download&id=abc123XYZ"
FORM = (
    '<form action="https://drive.usercontent.google.com/download">'
    '<input type="hidden" name="id" value="abc123XYZ">'
    '<input type="hidden" name="confirm" value="t"></form>'
)
HTML = {"content-type": "text/html"}


def _serve(monkeypatch, handler):
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record), follow_redirects=True)
    monkeypatch.setattr(streaming, "_get_shared_client", lambda: client)
    return seen


async def test_a_redirect_off_the_allowlist_is_never_requested(monkeypatch):
    seen = _serve(monkeypatch, lambda r: httpx.Response(302, headers={"location": "https://evil.example/x"}))
    with pytest.raises(ValueError, match="disallowed host"):
        await streaming._fetch_gdrive(URL, {})
    assert "evil.example" not in seen


async def test_an_allowed_redirect_hop_is_followed(monkeypatch):
    def handler(r):
        if r.url.host == "drive.google.com":
            return httpx.Response(302, headers={"location": "https://drive.usercontent.google.com/f"})
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"ID3")

    _serve(monkeypatch, handler)
    resp = await streaming._fetch_gdrive(URL, {})
    assert resp.status_code == 200
    await resp.aclose()


@pytest.mark.parametrize("status", [404, 500, 503])
async def test_an_error_page_after_the_confirm_retry_is_not_an_interstitial(monkeypatch, status):
    def handler(r):
        if r.url.host == "drive.google.com":
            return httpx.Response(200, headers=HTML, content=FORM.encode())
        return httpx.Response(status, headers=HTML, content=b"<html>nope</html>")

    _serve(monkeypatch, handler)
    resp = await streaming._fetch_gdrive(URL, {})
    assert resp.status_code == status
    await resp.aclose()


async def test_html_after_the_retry_with_a_200_is_still_an_interstitial(monkeypatch):
    def handler(r):
        return httpx.Response(200, headers=HTML, content=FORM.encode())

    _serve(monkeypatch, handler)
    with pytest.raises(streaming.GdriveInterstitialError):
        await streaming._fetch_gdrive(URL, {})


async def test_a_malformed_location_closes_the_response(monkeypatch):
    closed = []

    class Tracking(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b""

        async def aclose(self):
            closed.append(1)

    _serve(monkeypatch, lambda r: httpx.Response(302, headers={"location": "http://[bad"}, stream=Tracking()))
    with pytest.raises(ValueError):
        await streaming._fetch_gdrive(URL, {})
    assert closed
