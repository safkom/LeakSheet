# LeakSheet API Review (perf + accuracy) & Misc/Music-Videos Tabs

## Context

Follow-up to the completed iOS review. Two work streams, in order:
1. **API review** — improve performance (user's pain: cold first parse and refresh of known trackers) while *raising* parsing accuracy (user reports some songs/entries still parse wrong; wants them found systematically).
2. **Misc / Music Videos tabs** — some trackers have extra tabs (verified: Kendrick sheet has "🎥 Music Videos" gid=1743777120 and "💡 Misc." gid=1439258306; yetracker.net has "Misc"). Parse them separately from the main tracker and expose a single **"Misc" filter chip** in the iOS app showing type-labelled entries grouped under era headers (like the Recents view). iOS only this pass; API change must be backward-compatible.

**User decisions:** systematic accuracy hunt (no known-bad examples provided) · one combined Misc chip with per-entry type labels · iOS only · perf focus = cold parse + refresh · **Misc is a strict mode: misc and normal entries are never shown together; while Misc is on, Best Of/Recent (and search) filter within the misc list only.**

## Verified findings (exploration)

**Fetch pipeline waste (cold parse):** `async_fetch_and_parse` ([fetcher.py:1158](src/fetcher.py:1158)) `asyncio.gather`s **all** discovered GIDs before the parse loop early-breaks — yetracker exposes 17 tabs, so a cold parse can download ~17 multi-MB pages although the prioritized "Unreleased" tab almost always wins. No per-phase timing exists anywhere.

**Caching (refresh):** 3 tiers already exist — ETag/304, stale-while-revalidate (24 h, background refresh after 1 h), parsed-JSON file cache. iOS sends If-None-Match. Refresh slowness must be measured before fixing (suspects: cache misses from URL variants, revalidation not firing, gzip not applying to /sheet).

**Accuracy risk inventory (ranked, no test coverage):** slash-era fallback collisions (parser.py ~1157-1186) · image-only era header name backfill (~1306, 1425) · fuzzy era-match false positives (~1082-1123) · section-label heuristic can swallow sparse song rows (~772-827) · colspan cell shifts (~156-194) · unknown column headers silently drop fields (detect_columns + config.py COLUMN_ALIASES) · custom version tags (`[HQ Edit]`…) split songs (models.py VERSION_TAG_PATTERN). `parse_metadata.unmatched_rows` already collects up to 50 dropped rows per parse — a ready-made accuracy signal.

**Misc/MV tab shapes (fetched live):**
- Music Videos: `Era | Name | Notes | Media Length | Release Date | Type | Streaming (Yes/No) | Link(s)`
- Misc: `Era | Name | Notes | Media | Length | Date | Type | Available | Quality | Link(s)`
- Both era-grouped with header rows (stats + description) like the main tracker.

**Integration points:** named tabs come free from the htmlview shell (`_discover_named_tabs`); the art tab already demonstrates the exact secondary-tab pattern (`_get_art_tab_gid` → `_fetch_gid` → `parse_art_tab` in parallel). iOS `Codable` and web TS ignore unknown fields → `misc_entries` is backward-compatible. iOS UI reuses: FilterChip row, ArtistViewModel toggle pattern, recentsList era-grouped flat rendering, `playInList` continuation, SongDescriptionSheet.

---

## Implementation plan

Write this document (trimmed to spec form) to `docs/superpowers/specs/2026-07-05-api-review-misc-tabs-design.md` and commit before starting.

### Phase 1 — Accuracy (systematic hunt, then fixes)

1. **Verification harness** — new `tests/test_fixture_accuracy.py`, offline over the 4 `Trackers/` fixtures (Ye, Kendrick, Carti, Baby Keem). Per fixture:
   - Raw row census via `extract_table` vs parsed census via `parse_sheet` + `parse_metadata`.
   - Reconciliation assertions: row accounting identity (song + skipped + footer + header rows == total), skipped-rows ratio under a pinned baseline, zero empty eras (0 songs and no description), no song with ≥10 versions unless whitelisted, no duplicate era match keys, `fuzzy_matched_rows` pinned, every non-empty header cell either mapped by `detect_columns` or in an explicit known-ignored allowlist.
   - `LEAKSHEET_ACCURACY_VERBOSE=1` dumps unmatched rows / suspicious groupings for triage.
   - Additive `ParseMetadata` fields to support this: `unmatched_rows_total: int`, `dropped_columns: list[str]` (populated in `detect_columns` when a header matches no `COLUMN_ALIASES` entry).
2. **Regression tests for the ranked risks** (synthetic-HTML style in `tests/test_parser.py`): slash-era collisions, image-only era backfill, fuzzy-match false positives, sparse-song-row vs section-label, colspan shifts, unknown-column surfacing, custom version tags (`[HQ Edit]`).
3. **Fix loop** — fix only what the harness/tests surface (in `src/parser.py` + `COLUMN_ALIASES` in `src/config.py`); pin per-fixture song/era counts as constants so future parser changes fail loudly.

### Phase 2 — Performance (measure first)

4. **Timing instrumentation** — `_PhaseTimer` in `async_fetch_and_parse` ([fetcher.py:1057](src/fetcher.py:1057)): `base_fetch`, per-GID fetch, per-GID parse, `art_fetch/parse/verify`, cache read/write; one structured log line. Add a `Server-Timing` response header in the `/sheet` handler (api.py) so the client/curl can see phase costs.
5. **Baseline measurements** — cold `parse_sheet` on the Ye fixture; live curl timings for cold (`/cache/clear` first), warm, and 304 paths. Record numbers.
6. **Early-exit GID fetching** ([fetcher.py:1135-1192](src/fetcher.py:1135)) — replace gather-then-parse with: launch all `_fetch_gid` tasks, await in priority order parsing as each completes, cancel remaining tasks when the existing exit conditions hit (unreleased tab with ≥1 era, or ≥5 eras). Selection semantics unchanged (guarded by the Phase 1 harness). Async path only. One clean revertible commit, no env flag.
7. **Conditional wins, only if timings justify**: verify gzip actually applies to `/sheet` responses (curl with `Accept-Encoding: gzip`); cache pre-serialized JSON bytes alongside the parsed cache if `Artist.dict()` (5-10 MB rebuild per request) shows up hot; move/cached art pHash verification off the request path if material.
8. **Refresh path E2E** — verify the ETag round-trip (client quoting in [APIClient.swift:69](LeakSheet-iOS/LeakSheet/Services/APIClient.swift:69) vs `_parse_if_none_match`), that `APIError.notModified` consumers actually reuse the cached artist, that the etag persists across launches (CacheService), and that stale + background-revalidate transitions show in `X-Cache-Status`. Fix whatever is broken.

### Phase 3 — Misc / Music Videos tabs

9. **Model** (`src/models.py`) — `MiscEntry` (`era_name`, `name`, `notes`, `entry_type`, `date`, `length`, `available`, `quality`, `streaming: bool | None`, `links`, `source_tab: "misc"|"music_videos"`); `Artist.misc_entries: list[MiscEntry] = []`. Verify the custom `Artist.dict()` override (models.py:303) includes it.
10. **Parser** (`src/parser.py`) — `parse_misc_tab(html, kind) -> list[MiscEntry]` next to `parse_art_tab`, reusing `extract_table`; local column-alias map (don't perturb main-tab `COLUMN_ALIASES`); era grouping = track the last era-header row (same header grammar as main tab), literal era labels, no fuzzy matching. `Streaming` Yes/No → bool. Save the fetched real tab HTML (scratchpad `carti_mv.html` / `carti_misc.html`) as test fixtures.
11. **Fetcher** (`src/fetcher.py`) — `_MISC_TAB_NAMES` = {misc, misc., miscellaneous}, `_MV_TAB_NAMES` = {music videos, music video, videos, mvs} next to `_ART_TAB_NAMES` (same emoji-stripping normalizer — must handle "🎥 Music Videos", "💡 Misc."); fetch detected tabs with `_fetch_gid` in parallel with the art tab, parse in `to_thread`, fail-open like art; **exclude misc/MV GIDs from the main-tracker candidate list** in `_prioritize_gids` (also compounds the early-exit win). Caching unchanged (content-hash ETag covers the new field; pydantic default tolerates old cached blobs).
12. **iOS model** (`Models.swift`) — `MiscEntry` struct, `Artist.miscEntries: [MiscEntry]?` (`misc_entries`), optional like the `ogFilenames` precedent so old caches/servers decode. Streamability helper reusing `StreamResolver.isStreamableURL`.
13. **iOS VM** (`ArtistViewModel.swift`) — `misc` is a **mode switch, not a peer filter**: misc entries and normal entries are never shown together. When `misc` is ON the era list is fully replaced by `cachedMiscResults` (Misc+MV merged, interleaved by era in first-appearance order), and misc entries never leak into the normal views (recents/search/best-of operate on era data only when misc is OFF). While misc is ON, the other chips **filter within the misc list** instead of switching modes: *Recent* → sort/group misc entries by date descending; *Best Of* → restrict to entries carrying a best-of badge marker (no-op when none have one); *No Snippets* → drop entries whose `available`/`length` marks a snippet. Search while misc is ON searches misc entries only.
14. **iOS UI** (`ArtistView.swift` + new `Views/Artist/MiscEntryRowView.swift`) — "Misc" FilterChip **shown only when `miscEntries` is non-empty**; `miscList` modeled on `recentsList` (era headers with `eraColors`, tinted via `ensureReadable`); row shows name, type capsule (VIDEO/FREESTYLE/…), date, length, quality with a11y labels. Tap: streamable → synthesize a minimal `SongVersion` and play via `playInList` (continuation across the misc list); non-streamable → open first link externally. Info → `SongDescriptionSheet` with a synthesized version payload.

### Verification

- **Backend**: `python3 -m pytest tests/` green; harness baselines pinned; live curl of the Kendrick tracker → `misc_entries` populated from both tabs with `source_tab`/`entry_type`; yetracker.net → Misc entries; tracker without tabs → `[]`; before/after perf numbers recorded (target: eliminate the N−1 wasted GID fetches — 17 tabs on yetracker; warm/304 paths must not regress).
- **iOS**: build via `DEVELOPER_DIR=/Applications/Xcode-beta.app/... xcodebuild -destination 'generic/platform=iOS Simulator'` (no simulator runtime installed — interactive verification needs the iOS 27 runtime re-downloaded, else hand off checklist to user); old cached artist JSON still decodes; chip hidden for trackers without tabs.
- **Compat/rollback**: `misc_entries` additive+optional at every layer; backend can ship before iOS; early-exit and each parser fix are isolated revertible commits with pinned-count tests localizing regressions.

## Deliverables

1. Committed spec at `docs/superpowers/specs/2026-07-05-api-review-misc-tabs-design.md`.
2. Accuracy harness + fixes + regression tests (Phase 1), measured perf improvements (Phase 2), Misc feature end-to-end (Phase 3).
3. Final report: accuracy findings/fixes with counts, before/after timings, feature walkthrough, deferred items.
