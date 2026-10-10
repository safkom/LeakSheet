"""Every proxy endpoint answers an upstream failure with 404, 429 or 503, and logs it
below ERROR: a host being down is not an issue of ours, and a 5xx of ours would be.
"""

from __future__ import annotations

import logging

import httpx
import pytest

import src.api as api
import src.streaming as streaming

# (endpoint, query params, upstream URL prefix the request must hit)
_ENDPOINTS = {
    "stream-imgur": ("/stream", {"url": "https://imgur.gg/f/kYj3fdI"}),
    "stream-kraken": ("/stream", {"url": "https://krakenfiles.com/view/WS7wzkrklJ/file.html"}),
    "image-proxy": ("/image-proxy", {"url": "https://lh3.googleusercontent.com/abc=w120", "w": 320}),
    "metadata-imgur": ("/metadata", {"url": "https://imgur.gg/f/kYj3fdI"}),
    "metadata-froste": ("/metadata", {"url": "https://music.froste.lol/song/787da55acdae29149af5bef603e62ac5/play"}),
}

# upstream answer -> the status the client must see
_UPSTREAM = {
    "404": (httpx.Response(404, text="gone"), 404),
    "410": (httpx.Response(410, text="gone"), 404),
    "429": (httpx.Response(429, text="slow down"), 429),
    "500": (httpx.Response(500, text="boom"), 503),
    "503": (httpx.Response(503, text="down"), 503),
    "html-200": (httpx.Response(200, text="<html>challenge</html>", headers={"content-type": "text/html"}), 503),
}

# What the metadata API can't tell apart: it only knows the provider failed.
_METADATA_STATUS = {404: 503, 429: 503}


@pytest.fixture
def upstream(monkeypatch):
    def install(answer: httpx.Response) -> list[str]:
        hits: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(str(request.url))
            return httpx.Response(answer.status_code, content=answer.content, headers=answer.headers)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(api, "_get_shared_client", lambda: client)
        monkeypatch.setattr(streaming, "_get_shared_client", lambda: client)
        monkeypatch.setattr(api, "_get_proxy_client", lambda: client)
        return hits

    return install


@pytest.mark.parametrize("answer", _UPSTREAM, ids=str)
@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=str)
def test_upstream_failure_maps_to_a_client_status_and_no_error_log(
    api_client, upstream, caplog, endpoint, answer
):
    path, params = _ENDPOINTS[endpoint]
    response, expected = _UPSTREAM[answer]
    if path == "/metadata":
        expected = _METADATA_STATUS.get(expected, expected)
    hits = upstream(response)

    with caplog.at_level(logging.INFO):
        r = api_client.get(path, params=params)

    assert hits, "the request never reached the mocked upstream"
    assert r.status_code == expected, r.text
    errors = [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert not errors
