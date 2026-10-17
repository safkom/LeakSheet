"""Link rules shared with the Swift tests, so the two resolvers cannot drift apart.

The Python rules serve /stream and /sheet; the apps re-implement them (StreamResolver,
TrackerURLNormalizer) to decide what plays and which tracker a URL names. The expected
values come from the real Python functions over invented links; the Swift suite replays
the committed file (LeakSheetTests/Fixtures/stream_links.json). Regenerate it after an
intended rule change with: uv run python -m tests.parse.test_link_rule_contract
"""

from __future__ import annotations

import json

from src.config import ROOT_DIR
from src.fetcher import _normalize_url
from src.host_health import PROVIDERS, provider_for

FIXTURE = ROOT_DIR / "LeakSheet-iOS" / "LeakSheetTests" / "Fixtures" / "stream_links.json"

STREAM_LINKS = [
    # pillows: every alias, www, either scheme, and the tails a sheet carries
    "https://pillows.su/f/abc123",
    "https://www.pillows.su/f/abc123",
    "https://pillowcase.su/f/abc123",
    "https://www.pillowcase.su/f/abc123",
    "https://plwcse.top/f/abc123",
    "https://www.plwcse.top/f/abc123",
    "http://pillows.su/f/abc123",
    "https://pillows.su/f/a-b_C9",
    "https://pillows.su/f/abc123/extra",
    "https://pillows.su/f/abc123?x=1",
    "https://pillows.su/f/abc123#t=5",
    "https://pillows.su/f/abc123&sa=D&source=editors&ust=1&usg=X",
    # imgur
    "https://imgur.gg/f/AbC12",
    "https://temp.imgur.gg/f/AbC12",
    "https://www.imgur.gg/f/AbC12",
    "https://www.temp.imgur.gg/f/AbC12",
    # froste: the id is a hex hash
    "https://music.froste.lol/song/0123abcd",
    "https://music.froste.lol/song/0123ABCD",
    "https://music.froste.lol/song/0123abcd&sa=D&ust=1",
    # kraken
    "https://krakenfiles.com/view/AbC123xyz/file.html",
    "https://www.krakenfiles.com/view/AbC123xyz/file.html",
    "https://krakenfiles.com/view/AbC123xyz/file.html?x=1",
    # pixeldrain: single files only, ids are alphanumeric
    "https://pixeldrain.com/u/aBc123",
    "https://www.pixeldrain.com/u/aBc123",
    # drive: /file/d/{id}, /open?id= and /uc?id= (the id may sit anywhere in the query)
    "https://drive.google.com/file/d/1AbC-x_9",
    "https://drive.google.com/file/d/1AbC-x_9/view?usp=sharing",
    "https://www.drive.google.com/file/d/1AbC-x_9/view",
    "https://drive.google.com/open?id=1AbC-x_9",
    "https://drive.google.com/open?id=1AbC-x_9&usp=drive_copy",
    "https://drive.google.com/uc?id=1AbC-x_9&export=download",
    "https://drive.google.com/uc?export=download&id=1AbC-x_9",
    "https://www.drive.google.com/uc?id=1AbC-x_9",
    # case: hosts and the path keyword are case-insensitive, ids are not
    "HTTPS://PILLOWS.SU/F/ABC123",
    "https://Pillows.SU/f/AbC123",
    "https://PLWCSE.TOP/F/abc123",
    "https://IMGUR.GG/F/AbC12",
    "https://MUSIC.FROSTE.LOL/SONG/0123ABCD",
    "https://KrakenFiles.com/VIEW/AbC123xyz/FILE.HTML",
    "https://PIXELDRAIN.COM/U/aBc123",
    "https://DRIVE.GOOGLE.COM/FILE/D/1AbC-x_9",
    "https://Drive.Google.com/Open?id=1AbC-x_9",
    "https://drive.google.com/UC?id=1AbC-x_9",
    # not streamable: other hosts, lookalikes, wrong path shapes, missing or malformed ids
    "https://youtube.com/watch?v=abc",
    "https://mega.nz/file/abc",
    "https://example.com/a.mp3",
    "https://pillows.su/",
    "https://pillows.su/about",
    "https://pillow\u017f.su/f/abc123",
    "https://\u212arakenfiles.com/view/AbC123xyz/file.html",
    "https://pillows.su/f/",
    "https://pillows.su.evil.example/f/abc123",
    "https://evil.example/pillows.su/f/abc123",
    "https://notpillows.su/f/abc123",
    "https://plwcse.top/about",
    "https://notplwcse.top/f/abc123",
    "https://imgur.gg/about",
    "https://music.froste.lol/song/",
    "https://music.froste.lol/song/NOTHEX",
    "https://music.froste.lol/song/0123abcdzz",
    "https://music.froste.lol/song/０１２３",
    "https://froste.lol/song/0123abcd",
    "https://www.music.froste.lol/song/0123abcd",
    "https://krakenfiles.com/view/AbC123xyz/other",
    "https://krakenfiles.com/view/file.html",
    "https://pixeldrain.com/l/abc123",
    "https://pixeldrain.com/u/",
    "https://drive.google.com/drive/folders/1AbCdEf",
    "https://drive.google.com/open",
    "https://drive.google.com/open?id=abc/def",
    "https://drive.google.com/open?ID=1AbC-x_9",
    "https://drive.google.com/uc/x?id=1AbC-x_9",
    "https://drive.google.com/open/?id=1AbC-x_9",
    "ftp://pillows.su/f/abc123",
    "pillows.su/f/abc123",
    "",
]

TRACKER_URLS = [
    # a Google Sheet is its id: every spelling collapses to /htmlview
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/htmlview",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit#gid=0",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit?usp=sharing",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/view",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/pubhtml",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/pubhtml?gid=0&single=true",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/htmlview#gid=123",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/htmlview/sheet?headers=true&gid=1",
    "https://docs.google.com/spreadsheets/u/0/d/1AbC_d-42xYz/htmlview",
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz",
    "http://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
    "docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
    "  https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit  ",
    "HTTPS://DOCS.GOOGLE.COM/spreadsheets/d/1AbC_d-42xYz/edit",
    # userinfo and a default port don't change what is fetched
    "https://user:pw@docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
    "https://docs.google.com:443/spreadsheets/d/1AbC_d-42xYz/edit",
    "http://docs.google.com:80/spreadsheets/d/1AbC_d-42xYz/edit",
    # distinct sheets stay distinct
    "https://docs.google.com/spreadsheets/d/AAA/edit",
    "https://docs.google.com/spreadsheets/d/BBB/edit",
    # a sheet id counts only on docs.google.com: mirrors and lookalikes keep their identity
    "https://mirror.example/spreadsheets/d/1AbC_d-42xYz/edit",
    "https://docs.google.com.evil.example/spreadsheets/d/1AbC_d-42xYz/edit",
    "https://evil.example/?u=docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
    "https://evil.example/docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
    "https://docs.google.com/document/d/1AbC_d-42xYz/edit",
    # other hosts: scheme and host fold, the fragment goes, a bare host gets a slash
    "yetracker.net",
    "https://yetracker.net",
    "https://yetracker.net/",
    "yetracker.net/#top",
    "HTTPS://YETRACKER.NET/",
    "https://yetracker.net/other",
    "https://example.com/a?b=1",
    "https://example.com?b=1",
    "https://example.com/a#frag",
    "https://u:p@YeTracker.NET:443/#top",
    "https://example.com:8443/x",
    "https://example.com:80/x",
    "http://example.com:443/x",
    "http://EXAMPLE.com:80/x",
    "https://[::1]:8080/x",
]


def contract_payload() -> dict:
    return {
        "stream_links": [{"link": link, "provider": provider_for(link)} for link in STREAM_LINKS],
        "tracker_urls": [{"raw": raw, "normalized": _normalize_url(raw)} for raw in TRACKER_URLS],
    }


def test_the_shared_fixture_matches_the_python_rules():
    assert FIXTURE.exists() and json.loads(FIXTURE.read_text()) == contract_payload(), (
        "A link rule changed. Regenerate the Swift fixture: "
        "uv run python -m tests.parse.test_link_rule_contract"
    )


def test_the_vectors_cover_every_provider_and_the_unsupported_case():
    seen = {e["provider"] for e in contract_payload()["stream_links"]}
    assert seen == set(PROVIDERS) | {None}


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(contract_payload(), ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {FIXTURE}")
