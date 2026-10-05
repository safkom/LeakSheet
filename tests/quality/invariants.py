"""Properties a parsed Artist must satisfy, whatever tracker it came from.

This is the single definition of "the parse is sane". It exists because the
harness it replaces was self-referential: `tests/accuracy` pinned the parser's
own output as its own expectation, so a regression and an improvement produced
the same signal — "a delta to triage" — and known-wrong output was allowlisted
as correct (`KNOWN_DROPPED_COLUMNS`, `KNOWN_EMPTY_ERAS`).

Invariants need no baseline. They are things that are true of a correct parse
of ANY sheet, so they cannot rot, cannot be re-pinned to hide a regression, and
run against trackers nobody has hand-labelled.

Each check returns human-readable violations. Empty list means clean.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from src.models import Artist

# M:SS or H:MM:SS. Trackers also write "?:??" and "N/A" for unknown, which are
# legitimate content rather than parse failures, so they are allowed through.
_TIME_RE = re.compile(r"^\d{1,3}:[0-5]\d(:[0-5]\d)?$")
_UNKNOWN_TIME = re.compile(r"^(n/?a|\?+:?\?*|-|—|tbd|unknown)$", re.IGNORECASE)

# A leftover star means _split_compound_availability failed to strip a rating.
# Must be end-anchored and applied only to short values: a star ANYWHERE flags
# a description paragraph that happens to mention a "☆" in a mixtape title,
# which is source content, not a parse failure.
_TRAILING_STARS_RE = re.compile(r"[⭐★][\s⭐★☆]*$")
_MAX_AVAILABILITY_LEN = 40

# Names that are certainly not song names.
_JUNK_NAME_RES = (
    (re.compile(r"^\s*\d+\s*$"), "bare number (a track-number column read as the title)"),
    (re.compile(r"^\s*(19|20)\d{2}\s*$"), "bare year"),
    (re.compile(r"^https?://", re.IGNORECASE), "bare URL"),
    (re.compile(r"^#(REF|N/A|VALUE|DIV/0|NAME|NULL|NUM|ERROR)", re.IGNORECASE),
     "spreadsheet error value"),
)

# The four date formats the iOS client can parse are broader than this, but a
# value with no digit at all is never a date.
_HAS_DIGIT = re.compile(r"\d")


def check_row_accounting(artist: Artist) -> list[str]:
    """Every row must be accounted for in exactly one bucket.

    If this drifts, rows are being dropped or double-counted, which is silent
    data loss — the failure mode the old snapshot baselines could not see,
    because a lost row simply moved the pinned number.
    """
    md = artist.parse_metadata
    if md is None:
        return []
    out = []
    total = md.song_rows + md.skipped_rows + md.footer_rows + md.other_rows
    if total != md.total_rows:
        out.append(
            f"row accounting: {md.total_rows} total != {total} "
            f"(song={md.song_rows} skipped={md.skipped_rows} "
            f"footer={md.footer_rows} other={md.other_rows})"
        )
    if md.unmatched_rows_total != md.skipped_rows:
        out.append(
            f"unmatched counter out of sync: {md.unmatched_rows_total} "
            f"vs skipped {md.skipped_rows}"
        )
    for name, value in (("song", md.song_rows), ("skipped", md.skipped_rows),
                        ("footer", md.footer_rows), ("other", md.other_rows)):
        if value < 0:
            out.append(f"negative {name}_rows: {value} — classification double-counts")
    return out


def check_era_integrity(artist: Artist) -> list[str]:
    """Eras must be distinguishable and non-empty-by-accident."""
    out = []
    names = [e.name for e in artist.eras]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        # The iOS client keys Era by name (Era.id == name), so a duplicate
        # makes SwiftUI silently drop the second row.
        out.append(f"duplicate era names after disambiguation: {sorted(dupes)[:5]}")
    for era in artist.eras:
        if not era.name.strip():
            out.append("era with an empty name")
        songs = sum(len(s.songs) for s in era.sections)
        claimed = era.stats.total if era.stats else 0
        # Only a starved era is a defect. An era that is empty and claims
        # nothing is empty in the source — placeholder and future eras are
        # common and legitimate.
        if songs == 0 and claimed:
            out.append(f"era {era.name!r} claims {claimed} songs but parsed 0")
    return out


def check_art_urls(artist: Artist) -> list[str]:
    """Cover art must be a URL something can actually fetch."""
    out = []
    for era in artist.eras:
        if not era.art_url:
            continue
        parsed = urlparse(era.art_url)
        if not parsed.netloc:
            out.append(f"era {era.name!r} has a relative art_url: {era.art_url}")
        elif parsed.scheme not in ("http", "https"):
            out.append(f"era {era.name!r} art_url has scheme {parsed.scheme!r}")
    return out


def check_field_sanity(artist: Artist) -> list[str]:
    """Per-version values must be in their documented shape."""
    out = []
    for era in artist.eras:
        for section in era.sections:
            for song in section.songs:
                for label, why in _JUNK_NAME_RES:
                    if label.match(song.base_name):
                        out.append(f"song name {song.base_name!r} is a {why}")
                        break
                for v in song.versions:
                    if v.rating is not None and not 1 <= v.rating <= 5:
                        out.append(f"{song.base_name!r}: rating {v.rating} outside 1-5")
                    if v.track_length:
                        t = v.track_length.strip()
                        if not _TIME_RE.match(t) and not _UNKNOWN_TIME.match(t):
                            out.append(f"{song.base_name!r}: track_length {t!r} is not M:SS")
                    avail = (v.available_length or "").strip()
                    if (
                        avail
                        and len(avail) <= _MAX_AVAILABILITY_LEN
                        and v.rating is None
                        and _TRAILING_STARS_RE.search(avail)
                    ):
                        out.append(
                            f"{song.base_name!r}: star rating left in available_length "
                            f"{avail!r}"
                        )
                    for field in ("leak_date", "file_date", "date_of_recording"):
                        value = getattr(v, field, None)
                        if value and not _HAS_DIGIT.search(value):
                            out.append(f"{song.base_name!r}: {field} {value!r} has no digits")
    return out


def check_ios_contract(artist: Artist) -> list[str]:
    """Fields the Swift models declare non-optional must never be null.

    Checked on the serialized payload, which is what the app decodes: a null for a
    non-optional fails the whole payload, so one bad row takes down the tracker.
    """
    return ios_contract_violations(artist.model_dump())


def ios_contract_violations(payload: dict) -> list[str]:
    out: list[str] = []

    def need(d: dict, keys: list[str], ctx: str) -> None:
        out.extend(f"{ctx}: {k!r} is null/missing" for k in keys if d.get(k) is None)

    need(payload, ["name", "slug", "eras"], "Artist")
    for era in payload.get("eras") or []:
        need(era, ["name", "sections"], f"Era {era.get('name')!r}")
        for sec in era.get("sections") or []:
            need(sec, ["name", "songs"], f"Section in {era.get('name')!r}")
            for song in sec.get("songs") or []:
                need(song, ["base_name", "versions", "song_key"], f"Song in {era.get('name')!r}")
                if not song.get("versions"):
                    out.append(f"Song {song.get('base_name')!r} has no versions")
                for v in song.get("versions") or []:
                    need(v, ["name"], f"Version of {song.get('base_name')!r}")
                    for ref in v.get("sources") or []:
                        need(ref, ["label", "url"], f"SourceRef on {v.get('name')!r}")
    entries = list(payload.get("misc_entries") or [])
    for n in payload.get("notices") or []:
        need(n, ["text"], "Notice")
    for t in payload.get("tabs") or []:
        need(t, ["kind", "name", "entries"], f"TabSection {t.get('name')!r}")
        entries += t.get("entries") or []
    for m in entries:
        need(m, ["era_name", "name", "links", "source_tab"], f"Entry {m.get('name')!r}")
    return out


def check_tab_entry_identity(artist: Artist) -> list[str]:
    """Every entry in a tab must be distinguishable from its siblings.

    Clients key list rows on entry identity, and SwiftUI's ForEach keeps only
    the FIRST row per duplicate id — silently. Content alone does not identify
    these rows: a Stems tab lists ten entries called "Beat 1" under one era
    with no date, and 458 of the Ye tracker's 1,721 stem rows never rendered
    while the stats bar above them counted all 1,721.
    """
    out = []
    for tab in artist.tabs:
        seen = set()
        for entry in tab.entries:
            key = (entry.source_tab, entry.row_index, entry.era_name, entry.name)
            if key in seen:
                out.append(f"tab {tab.name!r}: duplicate entry identity {key!r}")
            seen.add(key)
    return out


ALL_CHECKS = (
    check_row_accounting,
    check_era_integrity,
    check_art_urls,
    check_field_sanity,
    check_ios_contract,
    check_tab_entry_identity,
)


def violations(artist: Artist) -> list[str]:
    """Run every invariant. Empty list means the parse is structurally sound."""
    out: list[str] = []
    for check in ALL_CHECKS:
        out.extend(check(artist))
    return out
