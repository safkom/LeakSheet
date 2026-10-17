"""/stream for krakenfiles.com: view page → CDN audio URL → bytes, offline."""
from __future__ import annotations

import httpx
import pytest

import src.api as api
import src.streaming as streaming
from src import host_health

VIEW = "https://krakenfiles.com/view/AbCdEf0123/file.html"
CDN = "https://hs0.krakenfiles.com/uploads/01-01-2030/AbCdEf0123/music.m4a"

# Layout of a live view page: og tags, waveform art, and the jPlayer media setup.
PAGE = f"""<!DOCTYPE html><html><head>
<meta property="og:image" content="https://hs0.krakenfiles.com/uploads/01-01-2030/AbCdEf0123/">
</head><body>
<img src="https://hs0.krakenfiles.com/uploads/01-01-2030/AbCdEf0123/waveform.png" >
<script>
$("#sfPlayer").jPlayer("setMedia", {{
    m4a: '{CDN}'
}});
</script></body></html>"""


@pytest.fixture
def kraken(monkeypatch):
    seen: list[httpx.Request] = []
    behaviour = {"page": httpx.Response(200, text=PAGE)}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "krakenfiles.com":
            answer = behaviour["page"]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return httpx.Response(
            206,
            content=b"\x00\x00",
            headers={"content-type": "audio/mp4", "content-range": "bytes 0-1/2"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(streaming, "_get_shared_client", lambda: client)
    monkeypatch.setattr(api, "_get_shared_client", lambda: client)
    return seen, behaviour


def test_stream_follows_the_page_to_the_cdn_with_a_referer(api_client, kraken):
    seen, _ = kraken
    r = api_client.get("/stream", params={"url": VIEW}, headers={"range": "bytes=0-1"})

    assert r.status_code == 206, r.text
    assert [str(q.url) for q in seen] == [VIEW, CDN]
    assert seen[1].headers["referer"] == "https://krakenfiles.com/"


def test_an_unreachable_page_marks_kraken_down_at_once(api_client, kraken):
    _, behaviour = kraken
    behaviour["page"] = httpx.ConnectError("refused")

    assert api_client.get("/stream", params={"url": VIEW}).status_code == 503
    assert host_health.down("kraken") is not None
