# LeakSheet iOS — Design & Correctness Review Fix Plan

## Context

The iOS app (LeakSheet-iOS, SwiftUI, iOS 27 target) is a music-tracker listening client for the FastAPI backend. The user requested a full review — design/UI first, then code correctness — plus fixes for 13 reported bugs. All bugs were root-caused by code inspection (3 explore agents + manual verification) and screenshot review (13 screenshots in `LeakSheet-iOS/App - current screenshots/`).

**User decisions:**
- Media controls: lock screen shows previous/play/next (like Apple Music); in-app Now Playing keeps prev/next AND gains ±15s skip buttons; skip amount lives in one constant.
- Design scope: **broader redesign** — also rework patterns that fight iOS 27 conventions, not just the listed bugs.
- Backend: API redesign is a later project, but parser fixes needed by these bugs are in scope now.

**Build environment (from memory):** `export DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer`; simulator "iPhone 17 Pro" (iOS 27), UI via Device Hub app; bundle id `si.safko.LeakSheet`.

---

## Root causes (all verified in code)

| # | Bug | Root cause | Where |
|---|-----|-----------|-------|
| 1 | Search hidden behind player bar | `.searchable` + `.searchToolbarBehavior(.minimize)` puts a floating search circle at the bottom; the mini player is a `safeAreaBar(edge: .bottom)` on the NavigationStack and renders over it | `ArtistView.swift:108-116`, `ContentView.swift:46` |
| 2 | Recents song ends → playback stops | Recents/search/description-sheet taps call `player.playTrack(...)` with **no context list**; `AudioEngine.playNext()` finds `eraSongs == nil` → `stopTrack()` | `ArtistView.swift:190, 354`, `SongDescriptionSheet.swift:210, 284`, `AudioEngine.swift:472-500` |
| 3 | Samples parsed wrong | Regex `_SAMPLES_PATTERN` terminates at first `.`/`,` (multiple samples collapse to one); artist-cleanup regexes (`\s+and\s+.+$` etc.) truncate names; emitted format `"Song" by Artist` embeds quotes which iOS then half-trims (`trimmingCharacters` only strips edge quotes → `Song" by Artist`) | `src/models.py:582-629`, `SongDescriptionSheet.swift:153` |
| 4 | OG file duplicated in description | Parser extracts `og_filename` but stores `notes` raw, so the "OG Filename: …" line stays in the notes text the app shows | `src/parser.py:1805-1836` |
| 5 | Only one OG file parsed | `og_filename: str \| None` (singular) + `.search()` returns first match only | `src/models.py:573-576, 589-597` |
| 6 | Lock screen shows 10s skips, no track buttons | `skipForward/skipBackwardCommand` registered with `preferredIntervals=[10]`; when skip commands are enabled the system shows them instead of next/prev | `AudioEngine.swift:582-597` |
| 7 | No ±15s skip in-app | Mini bar + Now Playing only have prev/play/next | `MiniPlayerBar.swift:75-111`, `NowPlayingView.swift:75-116` |
| 8 | Lock-screen title tap does nothing | No now-playing deep-link handling anywhere (no user activity / session handling) | app-wide |
| 9 | Era colors wrong (green for warm covers, red for white covers) | Winner-take-all 5-bit bucket count: a bright multi-tone cover fragments across many buckets while a small flat dark region wins; near-white filter (`bright>230 && colorfulness<20`) removes the true dominant | `EraColorExtractor.swift:76-112` |
| 10 | Era alt title looks unrelated | Alt names rendered as a bare subtitle with no "A.K.A." context, both collapsed and expanded | `EraCardView.swift:30-35, 100-107` |
| 11 | Krakenfiles won't play | iOS routing + backend allowlist are correct; backend scraper `resolve_kraken_cdn_url` regex (`…krakencloud.net/uploads/…/music.<ext>`) likely no longer matches the page HTML | `src/streaming.py:184-218` (verify live against https://krakenfiles.com/view/FJmpAhYHMp/file.html) |
| 12 | Quality button text unreadable | Now Playing quality chip is tinted with raw era color, no `ensureReadable` (which exists in `DesignTokens.swift:162` and is used elsewhere) against the accent gradient | `NowPlayingView.swift:134, 199-216` |
| 13 | Favourite broken in player / … menu | Two bugs: (a) heart-state check compares legacy `primaryVersionName` (always nil for new entries) to `track.name` → always unfilled; (b) player writes use `player.artistName.slugified` while song rows use API `artist.slug` → different keys, so toggling from the player duplicates instead of removing | `NowPlayingView.swift:155-164, 238-249`, `FavouritesManager.swift:94-96` |

**Additional issues found (in scope per "broader redesign"):**
- **A.** Nav-bar principal title overlaps the in-scroll custom header while scrolling (double title, see IMG_8464) — `ArtistView.swift:27-35, 82-93`.
- **B.** Landing shows artist "Creator, The Tyler" — name comes from backend `artist.name`; investigate name normalization in `src/parser.py` (likely a "X, The Y" reorder bug) and fix at source.
- **C.** Landing card stats truncate ("944 snipp…") — `RecentTrackerCardView`.
- **D.** Expanded multi-version songs (e.g. "Beat 5") show version rows with badges but no version label — `VersionRowView.swift`.
- **E.** Seek race: `AudioEngine.seekTo` sets `currentTime` before the async seek completes (slider flicker) — `AudioEngine.swift:140-144`.
- **F.** No route-change handling (headphones unplugged keeps playing) — AudioEngine.
- **G.** Accessibility: badge pills (`BadgeRowView`) and credit tags (`CreditTagsView`) have no VoiceOver labels.
- **H.** Description sheet "Links" header renders even when only the Play button follows (IMG_8463) — verify links-empty condition.
- **I.** Favourites from FavouritesView also play without context (same family as bug 2).

---

## Implementation plan

Ordered per user: design first, then correctness. Save this document (trimmed to spec form) to `docs/superpowers/specs/2026-07-04-ios-app-review-design.md` and commit before starting.

### Phase 1 — Design / UI (SwiftUI)

1. **Search placement** (`ArtistView.swift`, `ContentView.swift`)
   Move the search affordance into the navigation bar so it can never collide with the mini player: keep `.searchable(...)` but place it in the top bar (iOS 26+ toolbar search placement — `DefaultToolbarItem(kind: .search, placement: ...)` / `.searchToolbarBehavior`; confirm exact API against the iOS 27 SDK at implementation). Remove the bottom floating circle behavior. Verify the minimized state and active search field both clear the mini player.

2. **Artist header rework** (`ArtistView.swift:26-35, 81-93`)
   Replace the duplicated custom in-scroll title + `.principal` toolbar item with native `.navigationTitle(artist.name)` + `.navigationSubtitle("\(total) tracks")` and large-title collapse (`toolbarTitleDisplayMode`, keep `.toolbarMinimizeBehavior(.onScrollDown)`). Kills the double-title overlap (issue A).

3. **Era color extraction** (`EraColorExtractor.swift`)
   Replace winner-take-all bucketing with a proper dominant-color pick that matches the web app's ColorThief behavior: median-cut (MMCQ) over the sampled pixels, or minimally: score buckets by `count × saturation-weight` with the near-white filter relaxed, then pick the most populous *vibrant* cluster. Bump cache key `leaksheet_era_rgb_v2 → v3` so stale colors invalidate. Acceptance: "Before The College Dropout" resolves warm yellow/brown; "Yeezus 2" resolves light/neutral, not red.

4. **Era card alt titles** (`EraCardView.swift:30-35, 100-107`)
   Prefix with a styled "A.K.A." label (small caps / tertiary) in both collapsed and expanded states so alt names read as aliases, not a second title.

5. **Contrast hardening** (`NowPlayingView.swift`, `DesignTokens.swift`)
   Apply `ensureReadable(against:)` to the quality chip, slider tint, and any era-tinted foreground in Now Playing (compute against the actual gradient background, not `.lsBackground`). Audit other era-tinted text (recents era headers `ArtistView.swift:311`) the same way.

6. **Description sheet cleanup** (`SongDescriptionSheet.swift`)
   - OG files: render a dedicated full-width detail row "OG File" / "OG Files" (pluralized by count) listing all filenames from the new `ogFilenames` field (Phase 3).
   - Samples: drop the quote-trim hack (line 153); render the clean backend strings as a list.
   - Hide the "Links" header when there are no links (issue H).

7. **Version rows + landing polish**
   - `VersionRowView.swift`: show the version tag/label on each row (issue D).
   - `RecentTrackerCardView`: fix stat truncation (shorter labels or layout that fits, issue C).
   - Add VoiceOver labels to badge pills and credit tags (issue G).

### Phase 2 — Playback & media correctness

8. **Playback continuation context** (`AudioEngine.swift`, `PlayerViewModel.swift`, call sites)
   Generalize `eraSongs` into a playback context that any list can supply: recents, search results, description sheet, and favourites pass their visible ordered streamable versions (e.g. new `playInList(_:versions:...)` or reuse `EraSongContext` with a display-order list). Era lists keep current behavior including era-to-era rollover; list contexts continue down the list and stop at its end. Fixes bug 2 + issue I.

9. **Remote commands** (`AudioEngine.swift:557-597`)
   Remove/disable `skipForwardCommand`/`skipBackwardCommand` so the lock screen shows previous/play/next. Keep `changePlaybackPositionCommand`.

10. **In-app 15s skips** (`NowPlayingView.swift`, constant in `AudioEngine` or `DesignTokens`)
    Add `static let skipInterval: TimeInterval = 15`; add skip-back/skip-forward buttons (`15.arrow.trianglehead.counterclockwise` symbols) flanking prev/next in Now Playing. Mini bar stays prev/play/next (space-constrained).

11. **Now-playing deep link** (`LeakSheetApp.swift`, `AudioEngine.swift`)
    Investigate the iOS 27 SDK for a supported hook (MPNowPlayingSession / now-playing user activity). If a supported API exists, tapping the lock-screen title should land on the song's description sheet (via NowPlayingView). If not supported by public API, implement the closest supported behavior and document the limitation in the review report — do not fake it with on-foreground heuristics.

12. **Player identity for favourites** (`PlayerViewModel.swift`, `AudioEngine.swift`, `NowPlayingView.swift`)
    Carry `artistSlug` (and `sourceUrl`) through playback state so the player uses the canonical API slug. Fix the heart-state check to `favourites.isFavouritedByVersion(track, artistSlug: player.artistSlug, eraName: player.eraName)`. Fixes bug 13 in Now Playing + its … menu.

13. **Small correctness fixes** (`AudioEngine.swift`)
    - Update `currentTime` in the seek completion handler (issue E).
    - Pause on `AVAudioSession.routeChangeNotification` `.oldDeviceUnavailable` (issue F).

### Phase 3 — Backend parser fixes (scoped to these bugs)

14. **Samples extraction** (`src/models.py:578-629`, `tests/test_parser.py`)
    - Normalize smart quotes (U+201C/D, U+2018/19) to straight quotes before matching.
    - Rewrite extraction to capture *all* samples: iterate quoted-title occurrences after a "Samples" lead-in (don't terminate at `,`/`.`; handle "Samples "A" by X and "B" by Y" and comma-separated lists).
    - Fix artist cleanup so compound names survive (bounded lookaheads instead of `.+$` greediness).
    - Emit clean strings without wrapping quotes: `Title — Artist` (or `Title` alone). Update existing tests + add cases for multi-sample, smart quotes, compound artists.

15. **OG files** (`src/models.py`, `src/parser.py:1802-1848`, `src/api.py` serialization)
    - Add `og_filenames: list[str]` (use `.finditer()`); keep `og_filename` as first item for web-app compatibility.
    - Strip matched "OG Filename…" lines out of `notes` before storing, so descriptions no longer duplicate them.
    - Tests: multiple OG lines, OG line removed from notes, single-OG back-compat.

16. **Krakenfiles streaming** (`src/streaming.py:184-218`)
    Debug live against `https://krakenfiles.com/view/FJmpAhYHMp/file.html`: fetch the page, inspect where the audio CDN URL now lives, update `_KRAKEN_CDN_AUDIO_PATTERN`/headers accordingly, and add a parser-level unit test with a saved HTML fixture. Confirm the resolved CDN host passes the `/stream` allowlist (`src/api.py:228-238`) and extend it if the CDN domain changed.

17. **Artist name normalization** (issue B, `src/parser.py`)
    Find why "Tyler, The Creator" becomes "Creator, The Tyler" (likely a comma-reorder heuristic); fix and add a test.

18. **iOS model updates** (`Models.swift`, `APIClient.swift`)
    Decode `ogFilenames` (keep `ogFilename` fallback); no other API shape changes.

### Phase 4 — Verification

- **Backend:** `pytest tests/` (parser + api helpers); run the API and `curl` a real tracker sheet; confirm samples/OG JSON is clean; confirm the krakenfiles URL streams via `/stream`.
- **iOS build:** `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcodebuild -project LeakSheet-iOS/LeakSheet.xcodeproj -scheme LeakSheet -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build`.
- **iOS manual verification** (simulator via Device Hub + computer-use, per memory notes: drive with clicks, `left_click_drag` to scroll):
  - Search opens and is fully visible with a track playing.
  - Play a song from Recents → ends → advances down the list; era list still rolls into next era.
  - Lock screen (or Control Center in sim) shows prev/next; Now Playing shows 15s skips.
  - Era cards: warm cover → warm tint; white cover → neutral; quality chip readable on several era colors.
  - Favourite heart fills/unfills consistently from row, description sheet, Now Playing, … menu; no duplicate entries in `favourites.json`.
  - Description sheet: OG File(s) section pluralized, notes free of OG lines, samples list clean.
- **Regression:** web app still renders (samples/og_filename fields unchanged in shape), `glassEffect` console fault not worsened.
- Screenshot each fixed screen and compare against the "App - current screenshots" set in the final report.

## Deliverables

1. Committed design/review spec (`docs/superpowers/specs/2026-07-04-ios-app-review-design.md`) including the full findings table above.
2. Code fixes per phases 1–3, each verified per phase 4.
3. Final review report summarizing remaining/deferred findings (API redesign notes for the later API review, deep-link limitation if any).
