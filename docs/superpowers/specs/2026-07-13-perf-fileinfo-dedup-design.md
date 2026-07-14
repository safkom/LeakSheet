# LeakSheet: perf restructure, File Info feature, recents dedup, review + tracker verification

## Context

The iOS app freezes: toggling filter chips (Best Of / Recent / No Snippets) hangs for seconds, deep scrolling in Recents stutters, and opening a tracker blocks on downloading every era image at full resolution. The home screen shows duplicate "Recent tracker" cards for the same tracker opened via URL variants. The user also wants a File Info section (bitrate, codec, sample rate…) in the song description popup, sourced from provider metadata APIs (pillows.su etc.) with a player fallback.

Root causes were verified in code:

- **Chip freeze:** Best Of force-expands *all* eras (`ArtistViewModel.isEraExpanded` returns true when `bestOf`, `ArtistViewModel.swift:301-304`) while songs inside an era render in a **non-lazy `VStack`** (`Views/Artist/SongListView.swift:32-76`), and all filtering (`filteredEras` :103-122, `filteredSongs` :126-136, `filteredSections` :140-160, `miscResults` :340-371, `artistStats`/`eraStats` :383-412) is recomputed **synchronously on the main thread on every render**. Only Recents computes off-main with a cache (`computeRecentsAsync` :221-241).
- **Scroll lag:** per-render UIColor round-trips (`EraCardView.swift:131-160`, `ensureReadable` up to 20 conversions per header per render, `DesignTokens.swift:162-169`), `prefix(n)` re-slicing + full-list map on tap in Recents (`ArtistView.swift:391,449-452`).
- **Image slowness:** `prefetchEraImages` (`ArtistViewModel.swift:42-70`) eagerly downloads **every** era image on open (raced vs 5s sleep in `ArtistView.swift:113-143`); `ImageCache` decodes full-res with no downsampling (`ImageCache.swift:48`); backend `/image-proxy` (`src/api.py:505-551`) has no server cache, no resize, no ETag, and gzips already-compressed images.
- **Recents duplicates:** dedup by exact `sourceUrl` only (`RecentTrackersManager.swift:48`); backend echoes the *raw request URL* as `source_url` (`src/fetcher.py:1204+`), so URL variants (edit/htmlview/gid/query/scheme) duplicate.
- **File Info is half-built:** backend `/metadata` exists (`src/api.py:645-690`; parsers for pillows :578-617, froste :620-630, imgur :633-642; `resolve_metadata_url` `src/streaming.py:102-132`, no kraken branch). iOS `APIClient.fetchMetadata` (`APIClient.swift:116-136`) exists but is **unused** and returns non-Sendable `[String: Any]` — must become a typed model.

### Decisions locked with user
1. Recents dedup by **normalized URL** (not per-artist slug).
2. **Root-cause perf restructure** approved (may touch previously deferred ArtistView factoring).
3. At the end, **push to main** → DigitalOcean auto-deploys sheets.safko.eu (`.do/app.yaml`, `deploy_on_push: true`); verify live.

### Facts that shape the design
- Google `=s{px}` resizing works only for `lh3–lh6.googleusercontent.com`; `docs.google.com/sheets-images` only accepts `=s0`; `lh7-rt` can't resize (see `web/src/composables/usePlayer.ts:804-822`).
- Pillow is already a hard dependency (`requirements.txt`: `Pillow>=10.0.0`).
- `clear_cache()` (`src/fetcher.py:508-516`) unlinks every file in `.cache/` — image cache must be **flat files**, and add `is_file()` hardening.
- `agents.md` contains a stale "don't remove image loading wait — by design" note → update it (superseded by this plan).
- Census contract: regenerate snapshots via `python3 -m tests.tools.census --snapshots`; **never `--live` for gate diffs**. Live set = 7 trackers (`tests/tools/census.py:54-62`).
- Xcode 27 beta: export `DEVELOPER_DIR`; tests via `xcodebuild -project LeakSheet-iOS/LeakSheet.xcodeproj -scheme LeakSheet -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test`.

Order of work (user-specified): fixes + features → thorough code review → thorough tracker verification → deploy.

---

## Phase 0 — Baseline
1. Copy this plan to `docs/superpowers/specs/2026-07-13-perf-fileinfo-dedup-design.md`, commit.
2. `python3 -m pytest tests/` — record pass count.
3. iOS build+test green (command above).
4. `python3 -m tests.tools.census --snapshots`; confirm `git diff tests/results/census` clean.

## Phase A — Recent-tracker dedup by normalized URL (iOS)

**New:** `LeakSheet-iOS/LeakSheet/Utilities/TrackerURLNormalizer.swift` — `nonisolated enum` with pure `static func normalize(_ raw: String) -> String`, mirroring backend `_normalize_url` (`src/fetcher.py:165-193`):
- Trim; prepend `https://` if scheme missing; lowercase scheme+host.
- Google Sheets (`docs.google.com` + `/spreadsheets/`): extract sheet ID via `/spreadsheets/d/([A-Za-z0-9_-]+)/` and canonicalize to `https://docs.google.com/spreadsheets/d/{id}/htmlview` (collapses edit/view/htmlview, gid fragments, query params, scheme).
- Other hosts (yetracker.net): strip fragment; empty path → `https://host/`; otherwise keep path+query.
- Unparseable input → return trimmed input.

**Edit:** `LeakSheet-iOS/LeakSheet/ViewModels/RecentTrackersManager.swift`
- `RecentTracker.id` → normalized `sourceUrl`; when `sourceUrl` empty, fall back to `slug` (fixes distinct artists with missing URLs collapsing on `""`).
- Pure static `deduplicated(_ entries:) -> [RecentTracker]` — keep first (newest-first list) per normalized key, cap 20.
- `saveTracker`/`remove` compare by normalized key; `load()` runs `deduplicated` and re-saves if changed (**one-time migration** of persisted duplicates — must run before SwiftUI renders, so ForEach ids stay unique).
- Do NOT touch `CacheService` cache keying (would invalidate users' ETag caches).

**Tests:** new `LeakSheetTests/TrackerURLNormalizerTests.swift` (Swift Testing, parameterized like `StreamResolverTests`): Google URL variants collapse; yetracker variants collapse; distinct sheet IDs stay distinct; dedup keeps newest/caps/slug-fallback. Add file to test target.

## Phase B — File Info in song description sheet

No kraken metadata endpoint (page scrape has no format info) — player fallback covers it; note in a comment on `resolve_metadata_url`.

**B1 backend** (`src/api.py` metadata section ~:645): module-level in-memory TTL cache `{resolved_url: (ts, payload)}`, TTL 3600s, cap ~500 entries (evict oldest); `X-Cache-Status: hit|miss` header. Pytest (`tests/test_metadata.py`): `_parse_pillows_metadata` on delimiter-less + newline samples (channels digit and non-digit), `_parse_froste_metadata`, cache helper insert/expiry/cap.

**B2 iOS client** (`Services/APIClient.swift`): replace `[String: Any]` with `nonisolated struct FileMetadata: Codable, Sendable` — provider, container, codec, codecProfile, bitrate, sampleRate, bitsPerSample, duration, lossless (Bool?), channels (Int? — custom decode Int-or-numeric-String, backend emits both, `api.py:610`), froste fields (estimatedBitrate, frequencyCutoff, qualityMismatch), imgur fields (fileSize, mimeType, filename). Snake_case CodingKeys. 404 "no metadata API" → nil (not error noise).

**B3 player fallback** (`Services/AudioEngine.swift`): `nonisolated struct StreamFormatInfo: Sendable` (codec name from fourCC, sampleRateHz, channels, indicatedBitrateBps, trackKey). `private(set) var streamFormat` cleared on play/stop. In `.readyToPlay` branch of the status observer (~:367), spawn a MainActor task: `item.asset.load(.tracks)` → first audio track → `load(.formatDescriptions)` → `CMAudioFormatDescriptionGetStreamBasicDescription` (sample rate/channels) + `mediaSubType` fourCC; `item.accessLog()?.events.last?.indicatedBitrate` (≤0 → nil). Guard `currentTrack?.id == capturedKey` before assign (same pattern as `loadNowPlayingArtwork`). AVFoundation objects never cross actors — extract inline, store value type only. Expose via `PlayerViewModel.streamFormat`.

**B4 UI** (`Views/Shared/SongDescriptionSheet.swift`): `@State fileInfo: FileInfoState` (`idle/loading/loaded(rows, source)/unavailable`). New `fileInfoSection` after `detailGrid` (~:460) using existing `cardSection` helper (:491-499) + `LazyVGrid` matching detailGrid style. Rows from non-nil fields (Container, Codec+profile, Bitrate, Sample Rate, Bit Depth, Channels, Lossless, Duration; froste/imgur extras). Footnote "via pillows.su" / "from player". `.task` on presentation: streamable link → `fetchMetadata`; on nil/failure → if `player.currentTrack?.id == payload.version.id`, map `player.streamFormat` (source: player); else `.unavailable`. Inline `ProgressView` while loading (no layout jump).

**Tests:** `LeakSheetTests/FileMetadataDecodingTests.swift` — pillows/froste/imgur JSON fixtures, channels-as-Int and as-String, empty `{}`; fourCC→name mapper.

## Phase C — iOS performance restructure

### C1 Off-main filter pipeline (`ViewModels/ArtistViewModel.swift`)
New Sendable value types: `FilterState` (query, bestOf, noSnippets, recents, misc; Equatable), `FilteredEra` (era, sections, songs, stats), `FilteredContent` (state, eras, artistStats, recentResults, prebuilt recentPlaybackItems, miscResults). Make `Stats`, `RecentResult` Sendable.
- `private(set) var content: FilteredContent` — computed synchronously once in `init` with empty filter state (instant first frame).
- `applyFilters()`: cancel prior task, `isFiltering = true`, `Task.detached(.userInitiated)` → pure `nonisolated static computeContent(artist:state:)` (absorbs bodies of `filteredEras`, `filteredSongs/Sections`, `eraStats`, `artistStats`, `buildRecentResults`, `miscResults`; `Task.isCancelled` checks between eras). On main: **stale guard** `currentFilterState == state` before assigning (cancellation alone can race).
- `artistStats` keeps today's semantics (unfiltered totals) — compute once, cache in content.
- All chip toggles + search-debounce landing just mutate flags and call `applyFilters()`. Delete `computeRecentsAsync`, `cachedRecentResults`, `recentsLoading`, `invalidateRecentsCache`.
- Recents windowing moves into VM: `visibleRecents` stored array (initial 40, `loadMoreRecents()` +40, reset on new content) — kills per-render `prefix` slicing; tap uses prebuilt `recentPlaybackItems`.
- `searchResults(for:)` (overlay search) stays as-is (already debounced); fold into pipeline only if trivial.

`Views/Artist/ArtistView.swift`: read `vm.content.*` / `vm.visibleRecents` everywhere (stats bar, navigationSubtitle, erasList, recentsList, miscList). While `vm.isFiltering`: keep old content, thin progress indicator; chips flip instantly.

### C2 Lazy song rendering — flatten into outer LazyVStack
Nested same-axis lazy stacks don't defer, so **flatten**: row-model enum `EraRow: Identifiable` (`card/divider/groupHeader/sectionHeader/song/version/spacer`) built cheaply on main from `content.eras` + expansion state; rendered directly by the outer `LazyVStack` in `ArtistView.erasList`. Content-derived stable ids (`"era-…"`, `"song-\(era)-\(baseName)"`, `"ver-\(era)-\(version.id)"` — carry over stable-id work from 55fa649; watch duplicate baseNames across eras).
- `SongListView` dissolves; its row builders move into the row cases. `expandedSongs` `@State` moves into `ArtistViewModel` (lazy containers discard offscreen @State).
- Era-jump anchors stay on era cards (direct lazy children) — `ScrollViewReader` jumps keep working.
- Visual parity: per-row `eraColor.opacity(0.08)` background; last row of an expanded era gets bottom-rounded `UnevenRoundedRectangle` clip (screenshot QA before/after).
- `playWithEraContext` uses `FilteredEra.songs` (filtered versions excluded from auto-advance, as today). Best Of keeps all-eras-expanded semantics — now safe.

### C3 Precomputed era display colors
`nonisolated struct EraDisplayColors: Sendable` (dominant, title, body, border, gradient pair, readableHeader) + `static derive(from:)` doing the UIColor round-trips **once** (in `Utilities/DesignTokens.swift` or new file). VM: `eraDisplay: [String: EraDisplayColors]` + idempotent `setEraColor` — replaces `prefetchedColors` and view-local `eraColors`. `EraCardView` takes `displayColors` param (delete per-render math :131-160). Recents/misc headers read `eraDisplay[name]?.readableHeader` (kills 20-conversions-per-header).

### C4 Images — downsample + kill eager prefetch
`Services/ImageCache.swift`: `loadImage(from:maxPixelSize:)` decoding via ImageIO `CGImageSourceCreateThumbnailAtIndex` (`ThumbnailMaxPixelSize`, `FromImageAlways`, `WithTransform`); memory key `url#bucket`; buckets 128/320/640/1280 (`bucket(forPointSize:scale:)` helper). Call sites: era card 320, description sheet 640, row/mini thumbs 128, NowPlaying/lock-screen 1280. Delete `prefetchAll`.
`Utilities/EraColorExtractor.swift`: extract from 128px thumbnail (algorithm already downsamples to 100×100 internally); add sync `cachedColor(eraName:)` reader.
`ArtistViewModel`/`ArtistView`: delete `prefetchEraImages`, `imagesReady`, `prefetchedColors`, the 5s-race `withTaskGroup` (keep `player.setArtistEras` + initial activeEraColor). Seed `eraDisplay` from `cachedColor` at init; new colors arrive via `CachedEraImage.onColorExtracted` → `vm.setEraColor`.
Delete dead `Views/Artist/EraNavView.swift` (verified unreferenced; remove from project). Update stale `agents.md` line about image-loading wait.

### C5 Tests
New `LeakSheetTests/FilterPipelineTests.swift` on pure `computeContent` with a synthetic 2-era Artist fixture: bestOf era/version filtering, noSnippets drops, search matching (base/version/alt/era), recents ordering + playback-item alignment, per-era & artist stats, misc strict-switch semantics. Plus `EraDisplayColors.derive` sanity and bucket helper.

## Phase D — Backend image delivery (`src/api.py`)

1. **Gzip exclusion:** `_StreamSafeGZipMiddleware` (:287-324) skip set `{"/stream", "/image-proxy"}`.
2. **`proxy_image` (:505-551):** `w: int|None = Query(None, ge=32, le=1600)` snapped to buckets {128, 320, 640, 1280}. Module-level testable helpers:
   - `_rewrite_google_size(url, w)` — only `lh[3-6].googleusercontent.com`: strip `=[swh]\d+…` suffix, append `=s{w}` (mirror `enhanceGoogleImageUrl` regexes). None for lh7-rt / sheets-images / non-Google. **Allowlist check runs on the ORIGINAL url before rewrite/fetch** (rewrite never changes host/path — assert in test).
   - `_image_cache_key(url, w)` = sha256(f"{url}|{w or 0}").
   - `_resize_image_bytes(data, w, ct)` — Pillow thumbnail, JPEG q=82 / PNG-if-alpha, skip if already ≤w, skip if input >15MB (512MB instance), run in `asyncio.to_thread`.
   - Disk cache for resized results: **flat** `img_{key}.bin` + `img_{key}.meta.json` in existing `CACHE_DIR` (so `/cache/clear` clears them); 7-day TTL; evict oldest by mtime past 200MB. Harden `clear_cache` with `if f.is_file()`.
   - `ETag: "{cache_key}"` + honor `If-None-Match` → 304 (reuse `_parse_if_none_match`); `X-Cache-Status: hit|miss|origin`.
   - Flow: validate domain → if w & Google-resizable → fetch rewritten (passthrough on 200 image/*, fall back to original on failure) → else fetch original; if w → disk cache check → resize+store → serve.
3. **iOS:** `APIClient.imageProxyURL(for:width:)` appends `w`; `ImageCache` call sites pass their bucket. Google-rewrite logic lives server-side only.

**Tests:** new `tests/test_image_proxy.py` — rewrite helper matrix (lh3 with/without size suffix, lh7-rt→None, sheets-images→None, non-Google→None), resize helper on generated PIL images (width, aspect, alpha→PNG), cache-key stability, endpoint via `TestClient` with monkeypatched proxy client (w honored, second hit `X-Cache-Status: hit`, If-None-Match→304, disallowed domain rejected with w, no `Content-Encoding: gzip`).

## Phase H — /trackers endpoint + "Explore Trackers" on the main page (added mid-session by user)

The iOS Browse screen currently loads `https://assets.artistgrid.cx/artists.ndjson` (`BrowseArtistsView.swift:15`), which returns no results. Replace with our own API endpoint backed by the TrackerHub master sheet:
`https://docs.google.com/spreadsheets/u/0/d/1Z8aANbxXbnUGoZPRvJfWL3gz6jrzPPrwVt3d0c1iJ_4/htmlview/sheet?headers=true&gid=1884837542` — verified: single table, 1069 rows, columns [Trackers (name + Google-redirect link, ⭐/⭐️ prefix = featured), Credits, Up To Date?, Working Links?]. Existing `extract_table` parses it as-is.

**Backend** (`src/api.py` + `src/models.py`):
- `TrackerEntry` Pydantic model: `name`, `url`, `credit`, `best: bool`, `up_to_date: bool|None`, `working_links: bool|None`.
- Pure helpers: `_unwrap_google_redirect(url)` (parse `q` param of google.com/url, unquote; passthrough otherwise) and `_parse_trackerhub(html) -> list[TrackerEntry]` (header row detect, skip banner/empty rows, strip ⭐/⭐️ prefix → `best=True`, Yes/No → bool, rows require name + link).
- `GET /trackers`: fetch TrackerHub URL via the pooled sheets client, parse, in-memory TTL cache 3600s + stale-on-error fallback, `Cache-Control: public, max-age=3600`, `X-Cache-Status` header.
- Pytest: fixture HTML with banner rows, both star variants, redirect unwrap, missing-link row skipped; TTL/stale behavior of the cache helper.

**iOS**:
- `APIClient.fetchTrackers() -> [DiscoveryArtist]` — GET `{baseURL}/trackers`, decode (align field names with `DiscoveryArtist` at `Models.swift:518`; extend with `upToDate`/`workingLinks` if trivial).
- `BrowseArtistsView`: drop the ndjson loader, call `fetchTrackers()`; keep search/sort (best first, then name). Rename UI: "Browse Artists" → "Explore Trackers" on the landing button (`LandingView.swift:48`) and the sheet's navigation title.

**Note:** all iOS build/test/simulator work in every phase uses the **Xcode MCP** (`xcrun mcpbridge`; load the `device-interaction` skill to drive the simulator) instead of raw xcodebuild, per user instruction.

## Phase E — Thorough code review (before committing)

1. Run `/code-review` skill at **high** effort on the full working diff vs `e65ae0e`, weighing the prior fix range `13d635d..e65ae0e` (queue logic, favourites keys, stable ids) since Phase C touches the same surfaces.
2. Manual hot-path checklist: computeContent cancel/stale-guard race (A→B→A fast toggles); flattened ForEach id uniqueness (same baseName in two eras); `captureStreamFormat` vs track-advance race; `git diff src/api.py` shows **zero changes to /stream range logic**; image disk-cache concurrent-miss behavior (last-write-wins OK, note it); memory (≤1 decoded image in flight, no `resp.content` on stream path).
3. Fix confirmed findings; re-run both suites.

## Phase F — Thorough tracker verification

1. **Gates:** full pytest; census snapshots regen → `git diff tests/results/census` empty (parser untouched; any delta = red flag).
2. **Live API vs local server** (`uvicorn src.api:app --port 8080`) for the 7 locked trackers (ye/yetracker.net, travis, carti, kendrick, uzi, + the other census URLs in `tests/tools/census.py:54-62`): POST /sheet 200; era/song counts + skipped-ratio + notices vs committed census reports; spot-check descriptions, era art picks (Art-tab pHash upgrades), samples/og_filenames (ye), sources (travis) via `tests/tools/{quick_inspect,inspect_eras,inspect_songs,verify_live}.py`. Second request → `X-Cache-Status: hit`.
3. **Endpoint spot checks** with real links from census host histograms: `/metadata` for one pillows + froste + imgur link (fields, then `hit`); `/stream` ranges (`bytes=0-1023` → 206 + Content-Range; `bytes=-500` → 206 suffix); `/image-proxy?…&w=320` vs no-w (smaller length, ETag, 304 revalidate, no gzip).
4. **iOS visual pass** (iPhone 17 Pro simulator): Travis → Evidence section intact (open item) + File Info on a pillows version + kraken version shows player-fallback while playing; rapid chip-toggle session watching console for `glassEffect() tried to update multiple times per frame` (open item) and instant chip response; Ye (largest) → fast open, Best Of toggle without hang, deep Recents scroll past several pagination bumps, era expand/collapse animation + bottom-corner rounding QA; home screen → persisted duplicates collapsed after first launch, reopening via `/edit` variant doesn't duplicate. `xcodebuild … test` green.

## Phase G — Commit, push, verify deploy

Logical commits in order: (1) ios recents dedup, (2) ios filter pipeline, (3) ios flattened lazy rows, (4) ios era display colors, (5) ios image downsampling + dead-code removal + agents.md, (6) api image-proxy w/cache/ETag/gzip, (7) api metadata TTL cache, (8) ios File Info feature, (9) api /trackers endpoint, (10) ios Explore Trackers. Review fixes folded in as focused follow-ups.

Push to `main` → DO auto-deploy. Verify production: `https://sheets.safko.eu/api/docs` 200; POST /sheet (yetracker) headers (`X-Cache-Status`, `Server-Timing`, `ETag`); `/metadata` live + `hit` on repeat; `/image-proxy?…&w=320` downsized + ETag + no gzip + 304 revalidate; 2-minute iOS smoke against production.

## Risks
- **SwiftUI laziness:** flatten (not nest) lazy stacks; expansion state must live in VM; last-row corner rounding is the main visual-regression risk (explicit QA). Expand/collapse animation may need reducing to `.easeInOut(0.2)` if springs stutter.
- **Concurrency:** everything crossing `Task.detached` is Sendable value types; `FileMetadata` replaces non-Sendable `[String: Any]`; AVFoundation objects stay on MainActor; filter pipeline uses cancel **plus** state-equality stale guard.
- **512MB instance:** resize input cap 15MB, one image in flight per request, disk cache capped 200MB, metadata cache capped 500 entries; Google-side resize preferred so Pillow is the fallback path.
- **Compatibility:** `RecentTracker` JSON shape unchanged; `/sheet` + `/stream` responses byte-identical; `/image-proxy` + `/metadata` changes additive (web app unaffected).
