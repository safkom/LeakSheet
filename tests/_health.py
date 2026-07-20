"""The single source of truth for "is this parse healthy?".

Every check here derives from the parser's own ``ParseMetadata`` accounting and
the model fields — never from a re-implemented heuristic. Before this module the
suite carried 4-5 divergent definitions of a healthy parse (``test_fixture_accuracy``
skip <=1%, ``test_live`` skip >15% / fuzzy >20%, ``test_all_spreadsheets`` skip
>20% / >5%, ``census`` a fifth copy), which drifted apart and none of which was
the parser's own definition. Both the live invariant suite and any ad-hoc
validation import from here so there is exactly one definition.

These checks are **drift-tolerant** (ratios and accounting identities, never
exact counts) so they hold on live trackers that change daily. The exact-count
regression gate is a separate, opt-in concern — see ``tests/accuracy/`` and the
``accuracy`` marker.

Underscore-prefixed so pytest never collects it as a test module.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.models import Artist
from src.parser import _PLACEHOLDER_BASE_NAMES
from src.streaming import resolve_stream_url


@dataclass(frozen=True)
class Thresholds:
    """The one agreed tolerance for silent data loss and fuzzy matching."""

    max_skipped_ratio: float = 0.02   # >2% of data rows dropped == data loss
    max_fuzzy_ratio: float = 0.25     # >25% of song rows fuzzy-matched == suspect


DEFAULT = Thresholds()

# Relaxed tolerances for LIVE trackers, which drift daily and vary across 50+
# community maintainers. Used with include_advisory=False so only parse-break
# signals fail CI, not benign per-tracker quirks.
LIVE = Thresholds(max_skipped_ratio=0.15, max_fuzzy_ratio=0.40)


def iter_songs(artist: Artist):
    """Yield ``(era, song)`` across every section of every era."""
    for era in artist.eras:
        for song in era.songs:
            yield era, song


def is_streamable(url: str) -> bool:
    """Whether the backend ``/stream`` proxy can serve this link.

    Uses the *real* production resolver (``src.streaming.resolve_stream_url``)
    rather than a hand-maintained host set — the drift that ``census.py`` warned
    about in a code comment ("mirror of api.py allowlist, kept in sync manually").
    """
    return resolve_stream_url(url) is not None


def health_violations(
    artist: Artist,
    *,
    thresholds: Thresholds = DEFAULT,
    allow_empty_eras: frozenset[str] = frozenset(),
    include_advisory: bool = True,
) -> list[str]:
    """Return human-readable invariant violations; empty list means healthy.

    ``allow_empty_eras`` (lowercased era names) whitelists eras the source sheet
    itself leaves empty, so a faithful parse of a genuinely-empty era isn't
    flagged as data loss.

    ``include_advisory`` toggles the soft checks (unmapped columns, empty eras,
    duplicate era names, fuzzy ratio) that legitimately vary across live trackers.
    Strict callers (synthetic fixtures we fully control) keep them on; the live
    suite turns them off so only real parse breaks fail CI. The load-bearing
    invariants (eras/songs exist, row-accounting identity, skip ratio, starved
    eras, placeholder mis-grouping) always run.
    """
    v: list[str] = []
    md = artist.parse_metadata

    if not artist.eras:
        v.append("no eras parsed")
    if artist.total_songs == 0:
        v.append("no songs parsed")
    if md is None:
        v.append("no parse_metadata present")
        return v

    # --- Row-accounting identity: nothing may vanish silently ---
    computed_other = md.total_rows - md.song_rows - md.skipped_rows - md.footer_rows
    if computed_other < 0:
        v.append(
            f"row accounting is negative (double-counting): total={md.total_rows} "
            f"song={md.song_rows} skipped={md.skipped_rows} footer={md.footer_rows}"
        )
    if md.other_rows != max(0, computed_other):
        v.append(f"other_rows {md.other_rows} != computed structural {max(0, computed_other)}")
    if md.unmatched_rows_total != md.skipped_rows:
        v.append(
            f"unmatched_rows_total {md.unmatched_rows_total} out of sync with "
            f"skipped_rows {md.skipped_rows}"
        )

    # --- Silent data-loss ratios ---
    if md.total_rows > 0:
        skip_ratio = md.skipped_rows / md.total_rows
        if skip_ratio > thresholds.max_skipped_ratio:
            v.append(
                f"skipped ratio {skip_ratio:.1%} > {thresholds.max_skipped_ratio:.0%} "
                f"({md.skipped_rows}/{md.total_rows}); e.g. {md.unmatched_rows[:3]}"
            )
    if include_advisory and md.song_rows > 0:
        fuzzy_ratio = md.fuzzy_matched_rows / md.song_rows
        if fuzzy_ratio > thresholds.max_fuzzy_ratio:
            v.append(
                f"fuzzy-match ratio {fuzzy_ratio:.1%} > {thresholds.max_fuzzy_ratio:.0%} "
                f"({md.fuzzy_matched_rows}/{md.song_rows})"
            )

    # --- Unknown columns silently drop a whole field (advisory) ---
    if include_advisory and md.dropped_columns:
        v.append(f"unmapped header columns dropping data: {md.dropped_columns}")

    # --- Starved eras: stats claim songs but none parsed → era-routing bug ---
    starved = [
        e.name for e in artist.eras
        if e.song_count == 0 and e.stats is not None and e.stats.total > 0
        and e.name.strip().lower() not in allow_empty_eras
    ]
    if starved:
        v.append(f"eras whose stats claim songs but parsed 0: {starved}")

    # --- Empty eras: header recognized but nothing captured (advisory) ---
    if include_advisory:
        empty = [
            e.name for e in artist.eras
            if e.song_count == 0 and not e.description and not (e.timeline or [])
            and e.name.strip().lower() not in allow_empty_eras
        ]
        if empty:
            v.append(f"empty eras (recognized header, lost content): {empty}")

        # --- Duplicate era names → a mis-split header (advisory) ---
        counts = Counter(e.name.strip().lower() for e in artist.eras if e.name.strip())
        dupes = [k for k, c in counts.items() if c > 1]
        if dupes:
            v.append(f"duplicate era names: {dupes}")

    # --- Placeholder songs must never merge alt-title-less versions ---
    wrongly_grouped = [
        (era.name, song.base_name, len(song.versions))
        for era, song in iter_songs(artist)
        if song.base_name.lower() in _PLACEHOLDER_BASE_NAMES
        and len(song.versions) > 1
        and any(not (ver.alt_titles or []) for ver in song.versions)
    ]
    if wrongly_grouped:
        v.append(f"placeholder songs wrongly grouped: {wrongly_grouped}")

    return v


def assert_healthy(artist: Artist, **kwargs) -> None:
    """Assert the artist passes every invariant, listing all violations if not."""
    violations = health_violations(artist, **kwargs)
    assert not violations, (
        f"parse-health violations for {artist.name!r}:\n  - "
        + "\n  - ".join(violations)
    )


def live_violations(artist: Artist, *, allow_empty_eras: frozenset[str] = frozenset()) -> list[str]:
    """Critical-only, relaxed-tolerance check for live trackers.

    Runs the load-bearing invariants with LIVE thresholds and no advisory checks,
    so daily tracker drift doesn't produce false CI failures — only a genuine
    parse break (no eras/songs, broken row accounting, >15% dropped, starved
    eras, placeholder mis-grouping) fails.
    """
    return health_violations(
        artist, thresholds=LIVE, allow_empty_eras=allow_empty_eras, include_advisory=False
    )
