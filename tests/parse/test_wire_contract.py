"""One /sheet payload shared with the Swift tests, so the two sides cannot drift apart.

The payload comes from a synthetic parse through the real serializer. The Swift suite
decodes the same committed file (LeakSheetTests/Fixtures/contract.json). Regenerate it
after an intended wire change with: uv run python -m tests.parse.test_wire_contract
"""

from __future__ import annotations

import json

from src.config import ROOT_DIR
from src.fetcher import serialize_artist
from src.models import TabSection
from src.parser import parse_misc_tab, parse_sheet
from tests.quality.invariants import ios_contract_violations

FIXTURE = ROOT_DIR / "LeakSheet-iOS" / "LeakSheetTests" / "Fixtures" / "contract.json"


def _table(rows: list[list[str]]) -> str:
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table>{body}</table>"


_HEADER = ["Era", "Name", "Notes", "Track Length", "Leak Date", "What's Available?", "Sources", "Artist", "Link(s)"]
MAIN = _table([
    _HEADER,
    ["2 OG File(s)\n2 Full", "Contract Era", "(01/01/2001) (Start)", "", "", "", "", "", ""],
    ["", "Deluxe Sessions", "", "", "", "", "", "", ""],
    ["", "Early Takes", "(02/02/2002) (Sessions begin)", "", "", "", "", "", ""],
    ["Contract Era", "First Song [V1]\n(prod. Maker)", "first", "3:00", "Jan 1, 2020", "Full (HQ) ⭐⭐⭐⭐",
     '<a href="https://example.org/proof">Proof</a>', "Guest Performer", '<a href="https://pillows.su/f/aaa">aaa</a>'],
    ["", "Late Takes", "(03/03/2003) (Sessions end)", "", "", "", "", "", ""],
    ["Contract Era", "Second Song", "second", "2:00", "Jan 2, 2020", "Snippet", "", "", '<a href="https://pillows.su/f/bbb">bbb</a>'],
])
STEMS = _table([
    ["Era", "Name", "Notes", "Length", "Link(s)"],
    ["", "Contract Era", "", "", ""],
    ["", "Instrumentals", "", "", ""],
    ["Contract Era", "Beat 1", "demo", "1:44", '<a href="https://pillows.su/f/ccc">ccc</a>'],
])


def contract_payload() -> dict:
    artist = parse_sheet(MAIN, "Contract Artist")
    artist.tabs.append(TabSection(kind="stems", name="Stems", entries=parse_misc_tab(STEMS, "stems", ["Contract Era"])))
    body, _etag = serialize_artist(artist)
    return json.loads(body)


def test_section_notes_and_groups_reach_the_wire():
    sections = contract_payload()["eras"][0]["sections"]
    assert [(s["name"], s["group"], s.get("notes")) for s in sections] == [
        ("Early Takes", "Deluxe Sessions", "(02/02/2002) (Sessions begin)"),
        ("Late Takes", "Deluxe Sessions", "(03/03/2003) (Sessions end)"),
    ]


def test_the_payload_keeps_the_ios_hard_decode_contract():
    assert not ios_contract_violations(contract_payload())


def test_the_shared_fixture_matches_the_serializer():
    assert FIXTURE.exists() and json.loads(FIXTURE.read_text()) == contract_payload(), (
        "The /sheet wire format changed. Regenerate the Swift fixture: "
        "uv run python -m tests.parse.test_wire_contract"
    )


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(contract_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"wrote {FIXTURE}")
