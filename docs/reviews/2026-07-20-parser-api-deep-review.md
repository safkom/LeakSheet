# Deep Review: Parser / API backend — Google-Sheets retrieval, parsing, caching, images

**Date:** 2026-07-20 · **Scope:** `src/` on merged main (post-PR #10, `66f091d`) ·
**Method:** line-by-line source review + fresh 7-tracker census/snapshots + **live sweep of all
415 up-to-date TrackerHub trackers** (`scripts/tools/trackerhub_sweep.py`; artifacts in
`tests/results/sweep-20260720/`, gitignored) + iOS field-consumption audit (which fields the app
actually uses). Safety net: the rebuilt test pyramid (offline gate 456 · accuracy 158 · live 7).

## Summary

The pipeline is in good shape: retrieval (htmlview + gid discovery + tab prioritization),
parsing, image proxying, and the SWR/ETag caching stack are sound, and the fresh census shows
**zero dropped rows on all 11 pinned trackers**. The sweep surfaced one dominant defect class —
era-routing collisions that silently misattribute or starve songs — which this review fixed
(5 parser defects, 15 of the 34 unhealthy trackers fully cured), plus a vocabulary layer of
column/tab naming variants now mapped. The biggest *cross-layer* gap is date fidelity: 86% of
all dates use a format the iOS client can only sort by year.

## Critical issues — found, FIXED, and test-gated this session

| # | Where | Issue | Evidence / cure |
|---|-------|-------|-----------------|
| 1 | `parser.parse_sheet` fuzzy tier | **Sibling-era theft (fuzzy).** A row-era abbreviation ("GRODT OST") under its own header was stolen by a higher-scoring sibling ("Get Rich Or Die Tryin'", 4/4 words vs 4/5) — 12 songs misattributed, the real era starved. Fixed with a *positional prior*: fuzzy-match the current header first; first match registers the abbreviation for exact reuse. | 50 Cent + 7 more trackers cured; fuzzy baselines re-pinned (Ye 4→1, Carti 22→2) with **byte-identical song placement verified pre/post** |
| 2 | `parser.parse_sheet` exact tier | **Sibling-era theft (exact).** Version-tagged / slash-named sibling eras ("Fre3$tyle [V2]"/"[V3]", "38 Baby 2 [V1] / …") share a stripped key; bare rows under each header all routed to whichever sibling registered first. Fixed with a positional-*exact* prior over the era's own key forms (`_era_own_keys`). | NBA Youngboy 4→2 starved eras; test `TestSiblingEraKeyCollision` |
| 3 | `parser._is_era_header` | **Digit-leading era names rejected.** "38 Baby 2 [V1] / …" in a sparse header row was classed as stats-like (starts with digit) → era never created. Now only stats-keyword or pure-number lines are rejected. | test in `TestSiblingEraKeyCollision` (slash case) |
| 4 | `parser.parse_sheet` classification order | **Sparse era headers swallowed as section separators.** ≤2-cell header rows (stats + "Collaboration with X") hit the separator check before the era-header check. Header check now runs first — a genuine separator never carries era stats in col 0. | `TestStatsHeaderBeatsSeparator` |
| 5 | `parser.parse_sheet` auto-create branch | **Silent row loss.** Auto-creating an era from a song row *dropped the parsed version* (not even counted as skipped) in the current-era branch, while the no-current-era branch kept it. Branches now agree. | `TestNoSilentRowLossOnAutoCreate` |

## Vocabulary fixes (sweep-driven, user-confirmed) — FIXED

- `detect_columns` strips **trailing colons** ("Track Titles:", "Category:" — dropped whole
  columns on dozens of trackers; SosMula's entire grammar now parses).
- New `COLUMN_ALIASES`: `song`/`track titles`→name · `date`→leak_date (19 trackers) ·
  `release/leaked date`→leak_date · `record date`→date_of_recording ·
  `producer(s)`→producers column (name-cell credit wins) · `artist`/`credited artist`→ new
  additive `SongVersion.credited_artists` (performer, not feature) ·
  `file name`/`instrumental name`→og_filenames (merged with the notes convention, deduped).
- `_clean_tab_name` strips trailing `(WIP)`/`[WIP]` qualifiers (60+ tab occurrences) and
  normalizes slash spacing; `grails & wanted` variant added. Previously-invisible
  Released/Stems/Art/Misc (WIP) tabs now classify.
- `resolve_stream_url` miss logging downgraded WARNING→debug (normal content, flooded logs).
- New **iOS hard-decode contract test** (`tests/parse/test_ios_contract.py`): the fields whose
  null kills the entire app-side decode (`MiscEntry.links/source_tab`, `Song.base_name/versions`,
  `SongVersion.name`, `SourceRef.label/url`, …) are pinned at the serialized-payload level.

**Cure metric:** of the 34 trackers the sweep flagged unhealthy, **15 now parse fully healthy**;
372 of 415 were already healthy pre-fix → **387/415 (93%)** post-fix (remainder below).

## Caching review (the "50+ frequently-updated trackers" question)

Verdict: the architecture is right — file-cached HTML + parsed JSON, 1h fresh TTL, 24h
stale-while-revalidate serving raw bytes (no re-validation/re-serialization on the warm path),
ETag/304 with background refresh, and per-gid page caching. PR #10's serialize+hash off the
event loop closes the last warm-path stall. iOS adds a 7-day disk cache revalidated by ETag.
A tracker update propagates: ≤1h invisible; 1–24h served instantly stale + refreshed in the
background (next request is fresh); >24h refetched inline. For "often updated" trackers this is
the correct trade-off — the sweep measured cold fetches at 2–12s, which you never want inline.

Observations (ranked):
1. ~~🔴 **Sheet cache has no eviction.**~~ **IMPLEMENTED (addendum):** mtime-based, group-atomic
   size-cap eviction for `{hash}.html`/`.meta.json`/`.parsed.json` (default 1GB,
   `LEAKSHEET_SHEET_CACHE_MAX_BYTES` override), throttled to one dir scan/minute, hooked into
   both cache writes. Images keep their own 200MB cap. (`.cache/` had reached 770MB after one
   sweep.)
2. 🟡 **Single-flight only covers SWR revalidation** (`_revalidating`, per-process). Two
   concurrent *cold* misses for the same tracker both do the full fetch+parse. Low impact at
   current traffic (Procfile runs 1 worker, so per-process is fine today) — worth a lock if
   worker count ever grows.
3. 🟡 iOS never sends `force_refresh` and ignores `X-Cache-Status` — the app cannot show data
   age or offer pull-to-refresh. Backend supports both; purely a client follow-up.
4. ~~🟢 Proposal: scheduled prewarm~~ **IMPLEMENTED (addendum)** with a better cost profile than
   proposed: instead of sweeping the whole TrackerHub set (~415 fetches/hour), an hourly loop
   (`_prewarm_loop`, disable via `LEAKSHEET_PREWARM=0`) revalidates only cached parses inside
   the SWR gap — i.e. trackers people actually use — capped at 25/cycle, sequential, reusing
   the single-flight revalidator. Cost is proportional to real usage; stale-first UX disappears
   for active trackers.

## Tracker format differences (the 415-tracker evidence)

Full per-tracker matrix: `tests/results/sweep-20260720/*.json` (+ `_aggregate.json`).

- **Dates — the biggest cross-layer gap.** Of ~92k date values: 86% are `MMM d, yyyy`
  ("Mar 20, 2023") which the **iOS client could only parse to year precision**; only 9% were in
  a fully-parsed format; 2.5k have no year at all (sort to zero). → **IMPLEMENTED (addendum):**
  the iOS `parseLeakDate` now handles `MMM d, yyyy` / `MMMM d, yyyy` / `MMM yyyy` (pinned in
  `LeakSheetTests` `LeakDateParsingTests`), taking full-precision coverage from ~9% to ~95%.
  The ISO companion field (`leak_date_iso`) remains an option if non-iOS clients ever appear.
- **Availability/quality vocabulary** is 40+ values each but head-heavy (Full/Confirmed/OG
  File/Snippet cover 80%+; CD Quality/Not Available/High Quality/Recording/Lossless likewise).
  iOS colors by substring and handles the head well; tail values ("Full CDQ", "Confirmed") fall
  to grey — a canonicalization layer is possible but low-value; documented instead.
- **Link hosts:** 71.9% of ~100k links are app-streamable via the real `resolve_stream_url`.
  pillows.su dominates (42k), pixeldrain is already #2 (7.2k — PR #10's addition validated),
  then imgur.gg, YouTube (non-streamable), pillowcase, mega.nz (non-streamable, 3k — the
  largest non-streamable file host), GDrive, froste, krakenfiles.
- **Tabs:** after the (WIP)/separator fixes, the remaining unrecognized tab names are
  overwhelmingly *correctly excluded* non-song tabs (recent/key/tracklists/template/groupbuys).
  Candidates worth a future look: `samples` (9), `interviews` (14), `edits` (15), `media` (15),
  `unreleased discography` (7 — possibly a main-tab alias).
- **Structural grammars:** three families beyond the standard era-table: era-less flat
  tracklists (SosMula — now parses via aliases; Smino/Mag.Lo still empty), numbered-single
  sheets (Ice Spice [Alt]: `# | Title | Artist | Producer` with per-row "Released …" text), and
  template sheets never filled in (SpaceGhostPurrp "Album Name 4/5/6", KAYTRANADA "TBA").

## Remaining unhealthy trackers (19/415 — follow-up table)

| Class | Trackers | Assessment |
|---|---|---|
| Template/placeholder eras with dummy stats | SpaceGhostPurrp, KAYTRANADA "TBA", Carly Rae "Unknown Eras", Central Cee "Ongoing" | **RESOLVED (addendum):** data-side confirmed; `live_violations` now excuses placeholder-named eras (`_PLACEHOLDER_ERA_RE` in `tests/_health.py`, strict checks unaffected) — these 4 now report healthy (19/415 → 15/415 violating) |
| Per-era multi-tab workbooks | Smino, Mag.Lo, Avicii, ChaseSYNX, Underground Artists | **Re-diagnosed (addendum):** not flat tracklists — the "main" tab is a hub of era names/descriptions and *each era lives in its own sheet tab*. Supporting this = aggregating unrecognized era-named tabs into eras; a real feature needing a design decision |
| Numbered-single sheets | Ice Spice [Alt] (`# \| Title \| Artist \| Producer`, per-row "Released …" prose) | Distinct grammar; low tracker count; design decision |
| Per-tracker quirks | Radiohead (side-project eras), Glocky, J. Cole, Amerie, ILOVEMAKONNEN, NBA Youngboy (2 left), Pet Shop Boys, Rauw Alejandro, Creamer Nation | Individually triageable from sweep artifacts; diminishing returns this round |
| Dead links flagged working in TrackerHub | 9 fetch errors (401/403/404/410) | TrackerHub data quality; `/trackers` consumers could surface reachability |

## API payload observations (iOS audit)

Transmitted but never used by the app: `tracker_stats`, `parse_metadata`, `era.stats`/
`stats_raw`/`timeline`/`highlighted_producers`, `quality_color`, `available_length_color`,
`working_links`, `FileMetadata.artist/title`. The app recomputes stats and colors from strings.
No removal recommended without a deliberate API-version decision — but stop *extending* these
paths, and know that color extraction (`_extract_class_colors`) is pure overhead for the current
client. Host lists are now manually synced in three places (backend regexes, `_STREAM_ALLOWED_
DOMAINS`, iOS `StreamResolver`) — in sync today, drift-prone by construction.

## What looks good

- Row-accounting identity (`total == song + skipped + footer + other`) exposed in
  `parse_metadata` makes silent loss *measurable* — it is what caught every bug above.
- Tab prioritization (unreleased-first, art/content exclusion, misc-gid guard) survived 415
  real workbooks with zero wrong-tab selections observed.
- The SWR + raw-bytes warm path and the image pipeline (bucketed widths, Google-CDN resize
  first, atomic cache writes, decompression-bomb caps) are carefully engineered.
- pixeldrain/GDrive streaming (PR #10) is well-guarded: interstitial parsing, host allowlists,
  playable-content-type gate, 409/403 mapping.

## Verdict

**Approve** (current state) — the five defect classes found are fixed and test-gated; the rest
of the findings are proposals or documented follow-ups.

## Addendum — same-day implementation round (2026-07-20, user-approved)

Shipped from the ship list, each test-gated:
- **iOS date parsing**: `MMM d, yyyy` / `MMMM d, yyyy` / `MMM yyyy` formats added to
  `ArtistViewModel.parseLeakDate` (+ `LeakDateParsingTests`); full-precision date coverage
  ~9% → ~95% of live values.
- **Sheet-cache eviction**: 1GB size cap, group-atomic, throttled
  (`tests/unit/test_sheet_cache_eviction.py`).
- **Stale-cache prewarm loop**: hourly SWR-gap revalidation of actually-used trackers
  (`tests/api/test_prewarm.py`); `LEAKSHEET_PREWARM=0` to disable.
- **Misc-tab colon-suffixed headers** now parse (`_misc_header_key` matches the main-tab
  colon-strip).
- **Placeholder-era leniency** in live health checks (template scaffolding no longer reads as
  a starved-era bug): sweep violation count 19 → 15 of 415.
- Living docs (README, agents.md, iOS README/SPEC, web README) verified against code and
  refreshed (TrackerHub registry, pixeldrain/GDrive hosts, tab system, test pyramid,
  CacheService v2, media_kind).

Remaining next-round candidates, in order of user value: per-era multi-tab workbook support →
iOS pull-to-refresh + data-age surfacing (`X-Cache-Status`) → numbered-single grammar →
per-tracker quirk triage (sweep artifacts have the evidence).
