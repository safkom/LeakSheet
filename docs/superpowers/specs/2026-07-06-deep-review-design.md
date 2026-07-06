<!-- Approved by user 2026-07-06 via plan mode; execution began same day. -->
# LeakSheet Deep Review + Fix Cycle

## Context

Third and deepest review pass over LeakSheet (personal leaked-music tracker: FastAPI backend parses Google-Sheets trackers → SwiftUI iOS 27 app for listening + learning about songs). The July 4 iOS review and July 5 API/accuracy review landed their fixes; this cycle goes below them: a DEEP code review (correctness, cleanliness, best practices), a full UI review (HIG + iOS 27 conformance AND redesign where structure fights the listen-and-learn intent), a tracker deep-dive (census of content types, parse-error hunting, accuracy improvements), and an API review including security (service is publicly deployed at sheets.safko.eu, EU-geoblocked).

Review criteria are grounded in Apple's Xcode skill library (read in full this session): swiftui-specialist (view factoring = invalidation boundaries, @Observable granularity, ForEach identity, soft-deprecated APIs), swiftui-whats-new-27 (@State macro, AsyncImage HTTP caching, reorderable(), alert(item:), toolbar priorities), device-interaction (simulator verification), audit-xcode-security-settings, test-modernizer (Swift Testing).

**Locked decisions:** per-stream sequencing parser → API → iOS code → iOS UI, each review→fix→verify with a hard gate · every verified finding fixed this cycle (no parking) · 7 user-verified live trackers + 4 local fixtures for the census · redesign proposals get user sign-off before implementation · work on `main`, push at gates.

**Execution mode:** ultracode is on — review sweeps run as multi-agent workflows (parallel finders per dimension, adversarial verification of findings before they enter the fix list); fixes are applied in the main loop with test-first discipline.

**Step 0:** save this design (trimmed to spec form) to `docs/superpowers/specs/2026-07-06-deep-review-design.md`, commit it, commit/clean the dirty app-icon changes, gitignore `LeakSheet-iOS/build/` + `.DS_Store`.

---

## Stream 1 — Parser / Tracker Accuracy

### Review: census
New script `tests/tools/census.py` (generalize existing `tests/tools/` fetch-parse loop):
- Inputs: `--live` (the 7 locked URLs: yetracker.net + 6 Google htmlview links) and `--fixtures` (4 local snapshots). Flags: `--no-cache`, `--snapshot tests/fixtures/snapshots/`, `--out tests/results/census/`.
- Per-tracker artifact `<slug>.md` + `<slug>.json`: era table (sections, song/version counts, art), badge/version-tag/quality histograms, samples + OG-filename coverage, link-host histogram (vs `src/streaming.py` resolvers), full `ParseMetadata` dump (unmatched_rows, dropped_columns, fuzzy_matched_rows, skipped ratio), suspicion heuristics (0-song eras, ≥10-version songs, duplicate titles across eras, single-row eras, `???` placeholder clusters, era-looking song rows).
- Snapshot each live tracker's HTML during the run (fresh-today fixtures for pinning).

Triage all 11 reports; each anomaly → finding with tracker, row sample, suspected code path. Priority suspects: `_looks_like_era_name` (parser.py ~640, zero unit tests), `_fuzzy_era_match` (~1105) + `_era_match_key` (~1061), `_is_era_header`/`_is_section_separator`/`_is_dynamic_section_label`, `_merge_empty_stub_eras`/`_consolidate_group_labels` (placeholder grouping, recently touched), `detect_columns` vs dropped_columns. yetracker.net end-to-end (non-Google host) is checked first.

### Fix loop
Per finding: failing test first (parametrized `_looks_like_era_name` table from real census strings in `tests/test_parser.py`; pinned-count updates in `tests/test_fixture_accuracy.py` for structural fixes) → fix → full pytest. Baseline shifts must be justified in the same commit.

### Verify + pin (Gate P)
Pin new `SNAPSHOT_BASELINES` for the live-tracker snapshots (all 7 if size tolerates). Re-run census `--no-cache`; every delta from pre-fix reports must map to a logged finding. Exit: pytest green, skipped-ratio ≤1% on all 11, census diff clean.

## Stream 2 — API Correctness + Security

### Review targets
- **Security:** `POST /cache/clear` unauthenticated → require `Authorization: Bearer $LEAKSHEET_ADMIN_TOKEN` (deny by default when unset). CORS `allow_origins=["*"]` → explicit list (prod web origin + localhost:5173; iOS unaffected). SSRF: test `_is_allowed_domain` (api.py ~210-242) against IP literals, userinfo tricks, trailing dots, and redirect-following off-allowlist in `/image-proxy` + `/stream` — re-validate per hop or disable redirects. Rate limiting: lightweight in-process per-IP token bucket on `/sheet` + `/stream` (~40-line middleware; no external deps — low traffic, geoblocked).
- **Correctness:** Range synthesis (api.py ~697-930): suffix ranges `bytes=-N`, start ≥ length → 416, open-ended, upstream-ignores-Range, MIME-sniff with partial header bytes. Broad excepts: fetcher.py ~444 (`Exception` in tuple swallows all), ~1147/1338/1353; streaming.py ~287 `raise last_err` where `last_err` may be None. Cache key = sha256(URL) without canonicalization → normalize to `d/<id>/htmlview` before hashing, keep old-key read fallback one deploy cycle.

### Fix + verify (Gate A)
Tests in `tests/test_api_helpers.py` (Range matrix, allowlist bypass table, cache-key normalization table, auth). Local curl matrix (206/206/416 ranges, 401/200 cache-clear, 403 image-proxy on 169.254.169.254), then live matrix against sheets.safko.eu after deploy. Exit: pytest green, both curl matrices pass, web frontend loads under tightened CORS, iOS playback against prod unaffected.

## Stream 3 — iOS Code Correctness / Cleanliness

### Review (multi-agent sweep over all 38 Swift files, criteria from Apple skills)
- **View factoring:** ArtistView (444-ln body), SongDescriptionSheet (398), NowPlayingView (292) → separate `View` structs with narrow inputs (invalidation boundaries). Confirm with `-LogForEachSlowPath YES` before/after.
- **@Observable granularity:** PlayerViewModel mirrors ~26 AudioEngine props — measure with `Self._printChanges()` / Instruments, collapse to what the UI reads; check Equatable on stored-property types (setter short-circuit).
- **Sweeps:** ForEach identity (indices/`.self`/unstable ids), soft-deprecated APIs (foregroundColor, cornerRadius, edgesIgnoringSafeArea, …), @State-macro init pitfalls, unused @Environment reads, closure bindings → KeyPath/subscript bindings.
- **Known defects:** StreamResolver `fatalError` on regex compile → compile-checked `Regex` literals or log-and-skip; FavouritesManager baseName-suffix collision; `print()` → OSLog `Logger` (audio/network/cache categories); silent errors outside NowPlayingView → surface via `alert(item:)`.
- **ImageCache decision:** evaluate replacing custom ImageCache with iOS 27 AsyncImage HTTP caching + `asyncImageURLSession`; keep only if EraColorExtractor needs raw image access.
- **AudioEngine (recommendation: targeted decomposition, not full split):** extract pure decision logic (queue ordering, next/previous, auto-advance rules) into value-type `PlaybackQueueLogic` with characterization tests written BEFORE extraction; AVPlayer plumbing stays in the actor.
- **New `LeakSheetTests` Swift Testing target (yes, scoped to logic):** PlaybackQueueLogic, FavouritesManager (collision repro first), StreamResolver URL table, Models decoding against checked-in /sheet JSON, APIClient URL construction.
- **Bonus:** audit-xcode-security-settings pass (Enhanced Security entitlements; clang-warning step skipped — pure Swift).

### Fix order + verify (Gate C)
Test target scaffold → characterization tests → FavouritesManager → StreamResolver → OSLog sweep → view factoring → PlayerViewModel slimming → AudioEngine extraction last. Exit: build green (DEVELOPER_DIR=Xcode-beta, iPhone 17 Pro / iOS 27), `RunAllTests` green, no `print(` remains, simulator boots.

## Stream 4 — iOS UI (HIG/iOS-27 + Redesign)

### Audit protocol (device-interaction flow)
StartSession → InstallAndRun (si.safko.LeakSheet) → per screen: screenshot, UI-hierarchy dump (doubles as VoiceOver audit), synthesized taps via hierarchy centers. Screens: Landing (+RecentTrackerCard, Browse, TrackerInput), ArtistView (EraNav, StatsBar, SongList/SongRow/VersionRow/BadgeRow, Misc mode), SongDescriptionSheet, NowPlayingView + MiniPlayerBar, QueueSheet, FavouritesView, SettingsView, SongContextMenu.
Artifacts per screen: default screenshot, forced-light-scheme launch check (app is dark-only), Dynamic Type at AX3 (`simctl ui booted content_size`), hierarchy checked for missing labels (33 modifiers app-wide today), tap-rows without button traits, <44pt targets.
Checklist: touch targets, contrast, safeAreaBar/MiniPlayerBar behavior, sheet detents, loading/empty/error states, glassEffect per HIG, `reorderable()`/`reorderContainer` for QueueSheet, `alert(item:)` error surfacing, toolbar `visibilityPriority`.

### Redesign sign-off checkpoint (user approval per proposal, BEFORE implementation)
1. **ArtistView** — browse/stats/search/misc in one surface; candidate browse-vs-learn split.
2. **SongDescriptionSheet** — the "learn" surface: learning artifact vs data dump.
3. **NowPlayingView** — does "learn while listening" exist (song facts, era context inline)?
4. **QueueSheet** — reorder + auto-advance transparency.
Declined proposals fall back to minimal HIG-conformance fixes.

### Fix + verify (Gate U)
Implement approved redesigns + all conformance fixes; re-capture all artifacts; hierarchy diff. Exit: every interactive element labeled + trait-tagged, AX3 doesn't clip primary content, build + tests green.

## Final End-to-End Verification
1. Backend pytest green (non-live), one `-m live` run against prod.
2. iOS clean build + RunAllTests green.
3. Simulator smoke: paste live tracker URL → parse → browse 2 eras → SongDescriptionSheet → play (audio confirmed in console) → auto-advance → queue + reorder → favourite → relaunch → favourite persists, recents populated.
4. Prod smoke: iOS against sheets.safko.eu full flow.

## Git Discipline
Work on `main`; commit only with green local tests; push at gates. One commit per finding-fix with its test; baseline updates in the same commit as the parser change with rationale. Census script + snapshots committed before any parser fix. Prefixes: `fix(parser):`, `fix(api):`/`sec(api):`, `refactor(ios):`/`test(ios):`, `ui(ios):`.

## Highest-Risk Items → Extra Guards
1. **Parser era-matching/grouping changes** — pinned baselines on all 11 trackers BEFORE touching anything; census diff finding-explained; parametrized `_looks_like_era_name` table.
2. **Range/streaming changes** — pytest matrix + local & prod curl + simulator playback smoke before push.
3. **AudioEngine extraction** — characterization tests before extraction; play→advance→reorder→modes simulator flow after.
4. **CORS/auth tightening** — origin test from :5173 + prod web origin; 401 curl verified before deploy.
5. **Cache-key normalization** — unit table (gid/edit/htmlview/trailing-slash same vs different sheet IDs); old-key read fallback one deploy cycle.

## Critical Files
`src/parser.py` · `src/fetcher.py` · `src/api.py` · `src/streaming.py` · `tests/test_fixture_accuracy.py` · `tests/tools/census.py` (new) · `LeakSheet-iOS/LeakSheet/Services/AudioEngine.swift` · `ViewModels/PlayerViewModel.swift` · `Views/Artist/ArtistView.swift` · `Views/Shared/SongDescriptionSheet.swift` · `Views/Player/NowPlayingView.swift` · `Services/ImageCache.swift`

## Sequencing Estimate
Parser 3 sessions · API 2 · iOS code 2.5 · iOS UI 2.5 · E2E 0.5 ≈ **10-11 sessions**
