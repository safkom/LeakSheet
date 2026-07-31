# iOS app decisions

Why the non-obvious lines in `LeakSheet-iOS/LeakSheet/` look the way they do. Same
convention as [`../docs/decisions.md`](../docs/decisions.md): the source keeps a
one-line pointer, the archaeology lives here. Entries are keyed `File.swift::symbol`.

---

## ContentView.swift::safeAreaBar — bottom bar registration

`safeAreaBar` (not `overlay`) registers the mini player as a bottom bar, so the
system stacks the floating search field above it instead of laying it out
underneath, and scroll content is automatically inset to clear the bar.

## Models.swift::kept-badge — badge follows the versions actually shown

The row must wear a badge that belongs to the versions it actually shows. Carrying
the whole song's badge through made Best Of display 🗑️ on songs kept for a ✨ version
(Ye "Hurricane" in DONDA [V3]). Falls back to the song badge only when no kept
version carries one, so filters like No Snippets don't strip a song's badge entirely.

## APIClient.swift::chunked-download — chunked delegate download

`URLSession` hands the body over in Data chunks (one memcpy each). The previous
`AsyncBytes` loop iterated byte-at-a-time — ~8M suspension points on a Ye-size
payload, burning seconds of CPU after the network was already done.

## AudioEngine.swift::no-deinit-cleanup — NotificationCenter observers survive deinit

Intentional: `AudioEngine` is a process-lifetime singleton, and the
`@MainActor`-isolated, non-`Sendable` observer tokens cannot be safely touched from a
nonisolated `deinit` under Swift 6 isolation rules.

## AudioEngine.swift::early-video-hint — video hint from /metadata

The backend's stream-HEAD fallback knows the mime before `AVAsset` finishes loading
tracks, so the Now Playing surface can show video without a late swap. The asset's
own track list (`captureStreamFormat`) stays authoritative once loaded.

## AudioEngine.swift::bitrate-source — estimatedDataRate over accessLog

`estimatedDataRate` reflects the container's own bitrate metadata and is available
for progressive downloads right away — unlike `accessLog`'s `indicatedBitrate`, which
is an HLS-transfer metric that's typically empty for the plain HTTP files every
supported host serves.

## EraColorExtractor.swift::cache-key — keyed by art URL, not era name

Era names like "Unreleased" or "Singles" repeat across different artists, and a
bare-name key would let one artist's cached color leak onto another artist's
same-named era. The cache is keyed by the era's raw art URL instead — unique per
image — and colors are seeded from the persisted cache on load so cards and headers
are tinted on first paint without any image download.

## EraColorExtractor.swift::sample-filtering — ColorThief sample selection

Skips transparent and near-pure-white pixels only. A mostly-white cover keeps its
off-white pixels and resolves to a neutral, and a warm multi-tone cover isn't
out-voted by one small flat region (median cut groups similar tones into one box
instead of splitting them across hundreds of fixed buckets).

## ArtistViewModel.swift::song-ordinal — disambiguating same-baseName songs

`ordinal` is the song's position within its era's flattened song list. Leak trackers
deliberately emit several distinct "???"/"Unknown" tracks per era (the parser keeps
them separate), and without a positional key their `EraRow` ids collide, so SwiftUI's
`ForEach` silently drops the duplicates.

## ArtistViewModel.swift::filtering-indicator — honest spinner timing

Filtering is marked pending from the moment the query changes, not only after the
debounce fires — previously the spinner never appeared during the 200ms debounce
window, which is most of a fast query's total latency.

## ArtistViewModel.swift::single-flight-filter — serialized filter passes

Waits for the previous detached filter pass to actually stop before starting the
next one. Overlapping passes would race on the shared static `DateFormatter`s in
`parseDate` (`DateFormatter` isn't safe for concurrent use); serializing also means a
burst of chip/search changes only ever has one compute in flight instead of piling up
wasted work.

## ArtistViewModel.swift::no-sync-rebuild — no synchronous rebuildEraRows() on toggle

`isEraExpanded` treats a badge filter as "every era expanded", so rebuilding against
the still-stale (unfiltered) `content` would briefly render every song in every era.
`applyFilters()`'s completion rebuilds once `content` actually matches the new state.

## FavouritesManager.swift::concurrent-persist — why @concurrent is required

`@concurrent` forces `persist` off the caller's actor. Without it, under
`SWIFT_APPROACHABLE_CONCURRENCY` (SE-0461) a `nonisolated async` function runs on the
caller's actor — here the MainActor (`save()`'s `Task`) — so the encode + atomic write
would still block the main thread.

## FilterPipeline.swift::stable-row-id — content-derived id, not UUID()

A stable content-derived id lets SwiftUI's `ForEach` diff results across
filter/query changes instead of rebuilding every row each keystroke — a fresh
`UUID()` on every rebuild caused row flicker and lost expand state.

## FilterPipeline.swift::date-format-priority — dominant format tried first

`"Mar 20, 2023"` is the dominant format across live trackers (86% of all dated
versions in the 2026-07-20 TrackerHub sweep, incl. the whole Ye tracker). Without
prioritizing it, every such date degraded to year-only precision and Recents ordering
within a year was arbitrary. `"20 Mar 2023"` / `"20 March 2023"` (day-first ordering)
needs its own formatter too — none of the month-first formatters accept it.

## FilterPipeline.swift::iso8601-formatter — DateFormatter, not ISO8601DateFormatter

Full ISO-8601 with a time component (`"2023-03-20T14:30:00Z"`) is tried because the
web reference gets these free via `Date.parse`, while `_isoFmt`'s strict
`"yyyy-MM-dd"` rejects them — they fell back to the bare-year bucket without it.
`DateFormatter` is used instead of `ISO8601DateFormatter` because only the former is
`Sendable`, which a `nonisolated static` requires under Swift 6.

## RecentTrackersManager.swift::totalVersions-decode — backward-compatible decode

`totalVersions` was added after this type started persisting to `UserDefaults`, so
older entries on disk won't have it. Custom decode falls back to `totalSongs` rather
than dropping the whole decode (and silently wiping the user's recents list).

## RecentTrackersManager.swift::stats-source — single source of truth for stats

Delegates to `ArtistViewModel.computeEraStats` so the recents card and the artist
view never disagree — most notably that "confirmed" counts only non-streamable
versions (a streamable "Confirmed" version is really available, and was previously
double-reported here but not in the artist view).

## ArtistContentLists.swift::era-card-reuse — content tabs reuse EraCardView

Content tabs use literally the same `EraCardView` the main eras list uses (glass,
extracted era colors, cover art), so a content tab is visually a page of the same
app, not a different-looking list. Groups are prebuilt off-main in the filter
pipeline (`miscEraGroups`).

## ArtistRowViews.swift::glass-tint-opacity — tint via opacity, not color swap

Tinting via opacity keeps the glass effect structurally identical across states —
switching between `.clear` and a color changed the effect identity and tripped the
"glassEffect() tried to update multiple times per frame" fault on toggle.

## ArtistView.swift::content-state-branching — branch on computed state

Content branches follow the COMPUTED state (`content.state`), not the live chip
flags — the chips flip instantly while the previous content stays up until the new
one lands, so a branch never renders data computed for another mode.

## ArtistView.swift::search-field-placement — navigationBarDrawer, displayMode .always

`navigationBarDrawer` pins the search field under the navigation bar at the TOP of
the screen. The default iPhone placement (and the toolbar search item's minimized
form) both live in the bottom slot, where they end up behind the mini player
(`safeAreaBar`) — the drawer is the one placement that can never collide with it.
`displayMode .always` is required because the `.automatic` drawer minimizes into a
bare black capsule behind the Dynamic Island once content scrolls (audited
2026-07-13) — keeping the field visible avoids the glitch-looking pill and makes
search discoverable.

## EraCardView.swift::glass-gradient-layering — Liquid Glass + tinted gradient

Glass sits directly behind content (frosted refraction layer); the gradient is the
deeper background that bleeds through the glass. The glass shape stays constant; the
outer `clipShape(cardShape)` squares the bottom corners when expanded, so the glass
shape itself never animates — cheaper than reshaping the effect through the expand
spring, with an identical visual result.

## RecentTrackerCardView.swift::thumbnail-aspect-ratio — explicit 1:1 crop

Source art can be any aspect ratio; without an `aspectRatio` pin the row was
rendering a non-square 48×56.7 thumbnail (see U-6). Forced explicitly rather than
relying on the frame alone.

## RecentTrackerCardView.swift::stat-line-count — matches header count exactly

"N tracks" matches the artist header's `navigationSubtitle` exactly (both count total
versions, i.e. `ArtistViewModel.artistStats.total`) — previously this showed
`totalSongs` (unique song count), which reads as the same kind of number as the
header's count but disagrees with it for any tracker with multi-version songs (see
U-4).

## NowPlayingView.swift::original-label-width — pinned single-line width

The row's other controls compress this label until "Original" wraps onto a second
line inside the glass capsule; pinning it to one line at its natural width lets the
row lay out around it instead.

## NowPlayingView.swift::video-in-artwork-slot — video renders in the artwork slot

Video items (e.g. an `.mp4` behind an opaque pillows id) render their picture in
place of the artwork, driven by the same player as the audio path — sized to the
video's own aspect ratio (16:9 fallback until the track reports its size).

## FlowLayout.swift::clamped-sizing — measure and place against maxWidth, not .unspecified

An `.unspecified` proposal gives `Text` its full intrinsic (single-line) width, so a
long credit pill placed first in a row would report a size wider than the container
and never trigger the wrap check — and at placement time, an unspecified proposal
lets a wrap-capable pill re-expand to its full single-line intrinsic width and clip
off the trailing edge. Both measurement and placement clamp to `maxWidth` so
wrap-capable subviews (`Text`) report, and are placed at, the narrower multi-line
size they were sized for.
