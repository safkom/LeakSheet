"""Link rules shared with the Swift tests, so the two resolvers cannot drift apart.

The Python rules serve /stream and /sheet; the apps re-implement them (StreamResolver,
TrackerURLNormalizer) to decide what plays and which tracker a URL names. The expected
values come from the real Python functions over invented links; the Swift suite replays
the committed file (LeakSheetTests/Fixtures/stream_links.json). Regenerate it after an
intended rule change with: uv run python -m tests.parse.test_link_rule_contract

KNOWN_DIFFERENCES / KNOWN_URL_DIFFERENCES record where the two sides still disagree, with the
Swift answer pinned by hand: a change on either side fails a test until it is re-recorded or
the difference is closed and the case moves into the shared vectors.
"""

from __future__ import annotations

import json

from src.config import ROOT_DIR
from src.fetcher import InvalidURLError, _normalize_url
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
    "https://pillows.su/f/abc123/",
    "https://pillows.su/f/abc123/extra",
    "https://pillows.su/f/abc123?x=1",
    "https://pillows.su/f/abc123#t=5",
    "https://pillows.su/f/abc123&sa=D&source=editors&ust=1&usg=X",
    # the id is the leading run of id characters; whatever follows it never changes the file
    "https://pillows.su/f/abc123&keep=me",
    "https://pillows.su/f/abc.mp3",
    "https://pillows.su/f/abc123)",
    "https://pillows.su/f/abc123;x",
    "https://pillows.su/f/abc123 ",
    "https://pillows.su/f/abc\u00e9",
    "https://pillows.su/f/abc123\nhttps://pillows.su/f/def456",
    "https://pillows.su/f/abc123 https://pillows.su/f/def456",
    "https://pillows.su/f/abc123https://pillows.su/f/def456",
    "https://pillows.su/f/ab\tc",
    "https://pillows.su/f/abc%",
    "https://pillows.su/f/abc%zz",
    "https://pillows.su/f/abc%C3%A9",
    "https://pillows.su/f/abc[x]",
    "https://pillows.su/f/abc{x}",
    'https://pillows.su/f/abc"x',
    "https://pillows.su/f/abc<x>",
    "https://pillows.su/f/abc|x",
    "https://pillows.su/f/abc^x",
    "https://pillows.su/f/abc`x",
    "https://pillows.su/f/abc\\x",
    # imgur
    "https://imgur.gg/f/AbC12",
    "https://temp.imgur.gg/f/AbC12",
    "https://www.imgur.gg/f/AbC12",
    "https://www.temp.imgur.gg/f/AbC12",
    "https://imgur.gg/f/abc.png",
    # froste: the id is a hex hash
    "https://music.froste.lol/song/0123abcd",
    "https://music.froste.lol/song/0123ABCD",
    "https://music.froste.lol/song/0123abcd&sa=D&ust=1",
    "https://music.froste.lol/song/0123abcd.mp3",
    "https://music.froste.lol/song/0123abcd_x",
    # kraken
    "https://krakenfiles.com/view/AbC123xyz/file.html",
    "https://www.krakenfiles.com/view/AbC123xyz/file.html",
    "https://krakenfiles.com/view/AbC123xyz/file.html?x=1",
    "https://krakenfiles.com/view/AbC123xyz/file.htmlx",
    # pixeldrain: single files only, ids are alphanumeric
    "https://pixeldrain.com/u/aBc123",
    "https://www.pixeldrain.com/u/aBc123",
    "https://pixeldrain.com/u/a-b",
    "https://pixeldrain.com/u/a_b",
    "https://pixeldrain.com/u/abc.flac",
    # drive: /file/d/{id}, /open?id= and /uc?id= (the id may sit anywhere in the query)
    "https://drive.google.com/file/d/1AbC-x_9",
    "https://drive.google.com/file/d/1AbC-x_9/view?usp=sharing",
    "https://www.drive.google.com/file/d/1AbC-x_9/view",
    "https://drive.google.com/open?id=1AbC-x_9",
    "https://drive.google.com/open?id=1AbC-x_9&usp=drive_copy",
    "https://drive.google.com/open?id=1AbC-x_9#frag",
    "https://drive.google.com/uc?id=1AbC-x_9&export=download",
    "https://drive.google.com/uc?export=download&id=1AbC-x_9",
    "https://www.drive.google.com/uc?id=1AbC-x_9",
    "https://drive.google.com/file/d/abc.def",
    "https://drive.google.com/open?id=&id=1AbC-x_9",
    "https://drive.google.com/open?id=1AbC%2Dx",
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
    "https://drive.google.com/open?id=1AbC.mp3",
    "https://drive.google.com/open?id=1AbC+x",
    "https://drive.google.com/open?id=%0A&id=1AbC-x_9",
    "ftp://drive.google.com/open?id=1AbC-x_9",
    "ftp://drive.google.com/uc?id=1AbC-x_9",
    # tab, CR and LF break a query form (urlparse would drop them)
    "https://drive.google.com/open?id=1AbC%0A",
    "https://drive.google.com/open?id=1AbC-x_9\n",
    "https://drive.google.com/op\ten?id=1AbC-x_9",
    # a percent-escape in the path is never decoded into the literal shape
    "https://drive.google.com/%6Fpen?id=1AbC-x_9",
    "https://drive.google.com/file/%64/1AbC-x_9",
    "https://pillows.su/f/%61bc",
    "https://pillows.su/f%2Fabc123",
    "https://pillows.su/%66/abc123",
    "https://music.froste.lol/song/%30123abcd",
    "https://krakenfiles.com/view/AbC123xyz/file%2Ehtml",
    "https://pixeldrain.com/u/%61bc",
    # a port, userinfo, an escaped host or an empty path segment is not the literal shape
    "https://pillows.su:443/f/abc123",
    "https://pillows.su:/f/abc123",
    "https://user@pillows.su/f/abc123",
    "https://pillows%2Esu/f/abc123",
    "https://pillows.su//f/abc123",
    "https://pillows.su/f//abc123",
    "https://imgur.gg:443/f/AbC12",
    "https://music.froste.lol:443/song/0123abcd",
    "https://krakenfiles.com:443/view/AbC123xyz/file.html",
    "https://pixeldrain.com:443/u/aBc123",
    "https://drive.google.com:443/file/d/1AbC-x_9",
    "https://drive.google.com:443/open?id=1AbC-x_9",
    "https://user@drive.google.com/uc?id=1AbC-x_9",
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
    # a published sheet is its own id space: htmlview 404s for it, only pubhtml serves
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vAbC_d-9/pubhtml",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vAbC_d-9/pubhtml?gid=0&single=true",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vAbC_d-9/pubhtml#gid=5",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vAbC_d-9/pubhtml/sheet?headers=true&gid=1",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vAbC_d-9/pub?output=html",
    "https://docs.google.com/spreadsheets/u/0/d/e/2PACX-1vAbC_d-9/pubhtml",
    "docs.google.com/spreadsheets/d/e/2PACX-1vAbC_d-9/pubhtml",
    "https://docs.google.com/spreadsheets/d/e/AAA/pubhtml",
    "https://docs.google.com/spreadsheets/d/e1AbC/edit",
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
    # urlparse drops tab, CR and LF anywhere, so they don't change the tracker either
    "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/ed\nit",
    "https://docs.go\togle.com/spreadsheets/d/1AbC_d-42xYz/edit",
    "https://docs.google.com/spreadsheets/d/1AbC_\r\nd-42xYz/edit",
    "https://yetra\tcker.net/a\nb?c=\r1",
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
    "https://example.com/a?",
    "https://example.com/?",
    "https://example.com?",
    "https://u:p@YeTracker.NET:443/#top",
    "https://example.com:8443/x",
    "https://example.com:80/x",
    "http://example.com:443/x",
    "http://EXAMPLE.com:80/x",
    "https://[::1]:8080/x",
]


# (link, what Swift answers, why the sides differ). Swift may only be the stricter side.
KNOWN_DIFFERENCES = [
    (
        "https://drive.google.com/uc?id=%611AbC-x_9&x{=1",
        None,
        "Foundation re-escapes the % of a query that also holds an invalid character",
    ),
]

# (raw, what Swift answers, why). A Python result of None means InvalidURLError.
KNOWN_URL_DIFFERENCES = [
    ("https://example.com/a b", "https://example.com/a%20b", "Swift percent-encodes the path"),
    ("https://example.com/\u00e9", "https://example.com/%C3%A9", "Swift percent-encodes the path"),
    ("https://example.com/a?q=x y", "https://example.com/a?q=x%20y", "Swift percent-encodes the query"),
    ("https://b\u00fccher.example/x", "https://xn--bcher-kva.example/x", "Swift punycodes the host"),
    ("not a url at all", "https://not a url at all", "Swift cannot parse it and returns the input"),
    (
        "https://docs.google.com:99999/spreadsheets/d/ABC123/edit",
        "https://docs.google.com/spreadsheets/d/ABC123/htmlview",
        "Python rejects an out-of-range port",
    ),
    ("https://[::1/x", "https://[::1/x", "Python rejects an unclosed bracket"),
]


def _python_normalized(raw: str) -> str | None:
    try:
        return _normalize_url(raw)
    except InvalidURLError:
        return None


def contract_payload() -> dict:
    return {
        "stream_links": [{"link": link, "provider": provider_for(link)} for link in STREAM_LINKS],
        "tracker_urls": [{"raw": raw, "normalized": _normalize_url(raw)} for raw in TRACKER_URLS],
        "known_differences": [
            {"link": link, "python": provider_for(link), "swift": swift, "reason": reason}
            for link, swift, reason in KNOWN_DIFFERENCES
        ],
        "known_url_differences": [
            {"raw": raw, "python": _python_normalized(raw), "swift": swift, "reason": reason}
            for raw, swift, reason in KNOWN_URL_DIFFERENCES
        ],
    }


def test_the_shared_fixture_matches_the_python_rules():
    assert FIXTURE.exists()
    assert json.loads(FIXTURE.read_text()) == contract_payload(), (
        "A link rule changed. Regenerate the Swift fixture: "
        "uv run python -m tests.parse.test_link_rule_contract"
    )


def test_the_vectors_cover_every_provider_and_the_unsupported_case():
    seen = {e["provider"] for e in contract_payload()["stream_links"]}
    assert seen == set(PROVIDERS) | {None}


def test_a_known_difference_is_still_a_difference():
    payload = contract_payload()
    for entry in payload["known_differences"] + payload["known_url_differences"]:
        assert entry["python"] != entry["swift"], (
            f"{entry} no longer differs: move it into the shared vectors"
        )


def test_no_vector_is_also_a_known_difference():
    shared = set(STREAM_LINKS) | set(TRACKER_URLS)
    assert not shared & {e[0] for e in KNOWN_DIFFERENCES + KNOWN_URL_DIFFERENCES}


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(contract_payload(), ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {FIXTURE}")
