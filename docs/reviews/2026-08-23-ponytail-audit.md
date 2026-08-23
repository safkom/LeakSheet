# Ponytail audit — API + iOS, 2026-08-23

Scope: over-engineering and complexity only. Correctness and security findings from
the same pass were fixed in the parser-accuracy branch and are not repeated here.

Ranked biggest cut first. Every line count verified against the tree, not estimated.

## iOS / Shared (13,591 lines app+shared, 0 third-party deps)

- `native:` Three hand-rolled image loaders where the platform ships one. `ImageCache` (197) + `CachedImage` (64) + a third private copy `CachedEraImage` (`LeakSheet/Views/Artist/EraCardView.swift:206-244`) that duplicates `CachedImage` almost verbatim, differing only by a colour-extraction callback. `AsyncImage` appears **zero** times in the codebase. Replacement: `AsyncImage` + one `.task` for the colour callback. [~460 lines]
- `native:` `EraColorExtractor` (236) hand-rolls ColorThief — `CGContext` pixel sampling, median-cut to 3 levels / 8 boxes, its own LRU with an `insertionOrder` array, its own 200-entry eviction, its own 2-second debounced `UserDefaults` flush — to produce one dominant `Color` per cover. Replacement: sample a downscaled `CIAreaAverage`, or keep the extractor and drop the bespoke cache for `NSCache`. [~120 lines]
- `stdlib:` Nine `DateFormatter` singletons plus a regex fallback for one function (`Shared/ViewModels/FilterPipeline.swift:416-501`). Verified: exactly 9 `DateFormatter()` instances. Replacement: `Date.ParseStrategy` / `Date.ISO8601FormatStyle`, both unused today. [~70 lines]
- `yagni:` `PlayerViewModel` (116) is a pure facade over `AudioEngine.shared` — 32 `engine.` forwards, and its only original state is `seeking`/`seekValue`/`scrubPosition`. Both are `@MainActor @Observable` singletons, so views can observe `AudioEngine` directly. Replacement: move the three scrub properties onto `AudioEngine`, delete the wrapper. [~110 lines]
- `stdlib:` `ChunkedDownloadDelegate` (`Shared/Services/APIClient.swift:199-253`) is a 55-line `URLSessionDataDelegate` + `withCheckedThrowingContinuation` + `withTaskCancellationHandler` reimplementing `URLSession.data(for:delegate:)` to feed a progress label. DECISIONS.md justifies avoiding `AsyncBytes` (byte-at-a-time, slow) but `data(for:delegate:)` was the answer. [~55 lines]
- `yagni:` A third bespoke concurrency-limited task group. `ArtistViewModel.warmEraArt:365-410` writes its own 4-slot `withTaskGroup` scheduler duplicating `ImageCache.prefetch:106-122`. Dies with the `AsyncImage` migration. [~45 lines]
- `shrink:` Hand-rolled debounce four times, three different ways: `ArtistViewModel.scheduleDebounce` (200 ms), `FavouritesManager.save` (150 ms), `EraColorExtractor.scheduleFlush` (2 s), `ArtistViewModel.scheduleEraColorFlush`. Each is `task?.cancel()` + `Task.sleep` + `isCancelled`. Replacement: one `Debouncer` actor, or `AsyncStream.debounce`. [~40 lines]
- `delete:` `Tools/make-icons.swift` (591) is in no target — verified 0 references in `project.pbxproj` — and is not called by `build-ipa.sh`. Replacement: nothing; regenerate icons on demand from git history if ever needed. [591 lines]
- `delete:` `FavouritesManager.grouped()` (`:134-136`) is a one-line wrapper returning `groupedByArtist`; both call sites could use the property. `BadgeRowView` (10 lines) wraps `DedupedBadgePills` adding only a `SongVersion` unwrap. [~14 lines]
- `delete:` `FavouritesManager.orphanedTagRE` (`:341-344`) is a one-time migration regex still shipping, already self-flagged `ponytail: delete this once no install predates the change` — the only `ponytail:` marker in the iOS tree. [~10 lines]
- `yagni:` Two grouping indexes over the same data built in `Precomputed.init` (`ArtistViewModel.swift:236-240`): `songKeyEras` (keys spanning >1 era) and `baseNameEras` (every song), with `crossEraRefs` falling through one to the other. One index with a count check covers both.
- `yagni:` Six duplicated iOS/tvOS forks of the same screen — `SongDescriptionSheet`(641)↔`TVSongDetailView`(210), `QueueSheet`↔`TVQueueView`, `FavouritesView`↔`TVFavouritesView`, `SettingsView`↔`TVSettingsView`, `TrackerStatsSheet`↔`TVStatsView`, `BrowseArtistsView`↔`TVBrowseView` (the sort block is copy-pasted verbatim). Not a mechanical cut — tvOS focus differs — but the data-shaping halves are identical and belong in `Shared/`.
- `shrink:` `EraRow` is a hand-built flattened list model: an 8-case enum with composite string ids, a `markedLast(_:)` case-rewriting helper, and `rebuildEraRows()`/`appendSongRows()` (`ArtistViewModel.swift:662-739`) — a manual re-implementation of `List` + `Section`. Deliberate (it buys `LazyVStack` control) but worth re-testing against plain `List` on iOS 27.

**Not cut, deliberately:** zero custom protocols and zero `ObservableObject` in the whole tree — the abstraction layer is already thin. The over-engineering here is all hand-rolled infrastructure, not indirection.

## API / Python (9,052 lines)

- `delete:` `scripts/tools/quick_inspect.py` (39) hardcodes an 8-URL list that has diverged from both `tests/live_trackers.txt` and `census.LIVE_TRACKERS`. Replacement: `corpus_sweep --report`.
- `delete:` `scripts/tools/analyze_structure.py` (74), `deep_investigate.py` (77), `investigate_mismatch.py` (87), `debug_zero_eras.py` (71) — ad-hoc debug scripts, no argparse, referenced only by their own README line. Replacement: nothing; they were written to answer questions already answered. [~309 lines]
- `yagni:` The locked live-tracker list is duplicated between `tests/tools/census.py:55-63` and `tests/live_trackers.txt` with no shared loader, so they can drift silently. Replacement: read the txt file.
- `shrink:` `src/parser.py:1602` still claims "Extract cell background colors from the stylesheet" — no such code exists anywhere in `src/`. A comment that describes absent behaviour is worse than none.
- `shrink:` `src/parser.py` is 2,980 lines and `src/fetcher.py` 1,830. Not a cut in itself, but `parse_sheet` is a single ~400-line function whose row loop carries eleven era-matching branches; the era-matching rules are the part that most needs to be readable at 3am and currently aren't.

## Repo hygiene

- `delete:` `LeakSheet-iOS/build/` holds 2.0 GB across seven DerivedData trees plus a built `.ipa`. Gitignored (0 tracked files), so this is local disk, not repo weight — but it is 2 GB.
- `delete:` `docs/reviews/` is gitignored yet three review files are tracked from before the ignore was added. Either untrack them or stop ignoring the directory; right now the rule and the contents disagree.

---

net: **-1,700 lines and 0 deps possible on iOS** (the project already has zero third-party
dependencies — the win is native APIs replacing hand-rolled ones, not dependency removal),
**-350 lines on the API side**, plus 2.0 GB of local build output.

The single highest-value cut is the image stack: `AsyncImage` replaces roughly 460 lines
across three loaders, and taking it also deletes the duplicate task-group scheduler.
