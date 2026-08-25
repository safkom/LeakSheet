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

## TrackerLoader.swift::sticky-artist-name — the name follows the URL, not the entry point

`/sheet` derives the artist slug from the name it is given (`api.py`
`slug = slugify(req.artist_name)`), and favourites are keyed
`{artistSlug}::{eraName}::{baseName}`. Explore passed its curated name, but
reopening the same tracker from Recents (or by pasting the URL) passed nothing,
so the backend re-inferred the name from the page and returned a different
slug — every favourite saved through the other route silently stopped matching.
A sweep of the live corpus found 14 of 356 trackers where the curated and
inferred names disagree (e.g. `billie-eilish-alt-3` vs `billie-eilish`).

`load()` therefore resolves the name once, from the caller's override or else
from what Recents recorded for that normalized URL, so every entry point agrees.
`replayFromCache` additionally refuses a cached copy whose name disagrees with
the resolved one: the client caches the *response*, which already has any
override applied, so a mismatched copy carries the other slug and would
reintroduce the split on the 304 fast path.

The tradeoff is deliberate: a tracker renamed upstream keeps the name it was
first opened under for as long as it stays in Recents, because the alternative
is silently splitting the user's favourites in two. Removing the Recents entry
(swipe, or Clear All) drops the pin and the next open re-infers the name.

## PlaybackQueueLogic.swift::era-identity — era match excludes the version count

An era is located inside its artist's registered list by (name, artist, art
URL). The version count used to be a fourth **required** field, to disambiguate
two eras sharing a name — but the registered list is built once from the
**unfiltered** tracker (`ArtistViewModel.Precomputed.eraPlaybackContexts`) while
playback starts from the **currently filtered** list
(`ArtistContentLists.playWithEraContext`). Every era a chip had trimmed
therefore failed to match, `eraIndex` stayed nil, and auto-advance stopped at
the end of that era instead of rolling into the next one — with Best Of,
Grails, Worst Of or No Snippets on, playback died mid-tracker.

The count is still consulted, but only as a tiebreaker *among* eras that match
on all three identity fields (a tracker can carry two "Bonus Tracks" eras with
the same art — pinned by `duplicate era names disambiguate via recorded
position`). Requiring it broke the common case to serve the rare one; as a
tiebreaker it serves the rare case without touching the common one.

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

## Platform.swift::shim-surface — one shim file, not conditionals at call sites

Porting to macOS and tvOS needed exactly four cross-platform helpers: clipboard
access, a `CGImage` → platform-image bridge for `MPMediaItemArtwork`, URL-field
keyboard traits, and a pointer-hover highlight. Putting them in one file keeps
`#if os(...)` out of the ~20 call sites that use them. Everything else either
became platform-neutral outright (see the entries below) or forks inside a file
that was already platform-specific.

## DesignTokens.swift::color-resolve — resolve(in:) instead of UIColor(self)

`Color.rgbComponents` went through `UIColor(self)`, which has no macOS
equivalent, and it is the single chokepoint for `brightened`,
`relativeLuminance`, `contrastRatio`, `ensureReadable`, `preferredText` and
`blended`. SwiftUI's own `Color.resolve(in:)` is cross-platform, `nonisolated`,
and exact here because every colour in the file is a fixed literal — so
resolving against default `EnvironmentValues` cannot vary. `DesignTokensColorTests`
pins the resolved components so the derived contrast maths can't silently drift.

## ImageCache.swift::cgimage-currency — CGImage, not UIImage, end to end

The decode path was already `CGImage` (ImageIO's thumbnail API); `UIImage` was a
wrapper added at the end and unwrapped again by every consumer. Making `CGImage`
the currency type de-UIKits `ImageCache`, `EraColorExtractor`, `CachedImage`,
`EraCardView` and `AudioEngine.makeArtwork` at once, with no conditional
compilation anywhere. `Image(decorative:scale:)` renders identically to
`Image(uiImage:)` here — `UIImage(cgImage:)` already defaulted to scale 1 and
`.resizable()` discards intrinsic size.

The memory-warning observer became a **retained** `DispatchSourceMemoryPressure`.
`UIApplication.didReceiveMemoryWarningNotification` has no macOS analogue, and
unlike the old fire-and-forget NotificationCenter observer a DispatchSource is
cancelled as soon as its last reference drops — hence the stored property.

## AudioEngine.swift::audio-session-fork — guard on os(macOS), never os(iOS)

Only macOS lacks `AVAudioSession`. tvOS 27 has the complete API *including* the
iOS-27 forms this app depends on (`activate(options:)`,
`didBecomeInactiveNotification` + `deactivationContextKey`,
`resumptionRecommendationNotification` + `resumptionContextKey`). Writing these
guards as `#if os(iOS)` would silently strip interruption handling and session
activation from Apple TV, where background audio is a headline feature.

## Toolbar placements — .primaryAction / .confirmationAction, not .topBar*

`.topBarLeading` and `.topBarTrailing` do not exist on macOS. Rather than shim a
`platformTrailing` placement, the 16 call sites moved to `.primaryAction`,
`.confirmationAction` and `.cancellationAction`, which exist on all three
platforms and are semantically what those buttons already were. iOS renders
identically; on a Mac sheet `.confirmationAction` correctly lands in the
bottom-right button row instead of a toolbar the sheet doesn't have.

## contentShape goes INSIDE a .plain Button's label

`.buttonStyle(.plain)` hit-tests only its drawn content. A row-shaped Button
whose label ends in a `Spacer()` is therefore dead in the empty space — on macOS,
clicking a few pixels past a short tracker name did nothing at all. Applying
`.contentShape(Rectangle())` *outside* the Button does not fix it: the gesture is
attached to the label, not to the modified view. It has to go on the label's root,
which is what the pre-existing working usages in `ArtistRowViews` and
`MiniPlayerBar` already did.

## SongDetailPayload — model data, not a type nested in a view

`FavouritesManager` built a `SongDescriptionSheet.Payload`, so a view model
depended on a view. The payload is pure model data and the tvOS detail screen
needs it too, so it moved to `Shared/Models`. `SongDescriptionSheet.Payload`
remains a typealias, leaving the iOS call sites untouched.

## Shared/ is a root folder, not a membershipExceptions list

The tvOS target was meant to take the existing `LeakSheet/` folder and exclude
`Views/` via a folder-sync `membershipExceptions` entry. A bare directory name
there is silently ignored — every iOS view compiled into tvOS and the build died
on `import WebKit`, which does not exist in the tvOS SDK. Moving the shared code
into its own root group makes the boundary explicit and needs no exceptions.

## tvOS::no-swipe-no-context-menu — actions live on a detail screen

`swipeActions`, `swipeActionsContainer()` and `contextMenu` are all unavailable
on tvOS, and they are how iOS exposes play / queue / favourite / details. On tvOS
each row carries a second, explicitly focusable info button that pushes
`TVSongDetailView`, where those actions are ordinary buttons. Selecting the row
itself still plays, which is the common case from a couch.

## tvOS::qr-handoff — web links become QR codes

WebKit is absent from the tvOS SDK entirely and tvOS has no browser to hand off
to, so `EmbedPlayerView` and `SafariView` have no tvOS equivalents. Rather than
hide the content or show dead rows, a link renders a QR code the user scans to
continue on their phone. Routing happens at the existing `MiscLinkClassifier`
boundary, so there is no second copy of the link-classification logic.

## make-icons.swift::note-punch — destinationOut per component

The note is punched out of the droplet inside a transparency layer, one
component at a time. A single even-odd fill against the droplet re-fills the
head/stem/flag overlaps and leaves notches; a single non-zero fill cancels where
the flag crosses the stem, because the flag is authored in the opposite winding
direction to the CG-generated ellipse and rounded rect. Punching each component
separately makes the hole their union regardless of winding.

## make-icons.swift::ios-entries-have-no-scale

The iOS app-icon entries deliberately omit the `scale` key. Its absence is what
marks them as the modern single-size icon; with `"scale": "1x"` present, actool
treats them as legacy sized slots and warns that the 1024, 60@2x, 76@2x and
83.5@2x icons are all missing.

## make-icons.swift::tvos-layer-order — layers are front-to-back

An `.imagestack`'s `layers` array is ordered FRONT to BACK, and actool requires
the LAST entry — the backmost layer — to be a fully opaque bitmap. That is the
reverse of the natural back-to-front drawing order, so the array is reversed on
write. (`Array(...)` matters: JSONSerialization cannot serialize a
`ReversedCollection`.)

## MacRootView.swift::selection-shell — sidebar selection, not a push stack

The detail column is driven by the sidebar selection; there is no
`NavigationStack`. The push-stack shape it replaced had to clear its path on
every section change to dodge a crash (the stack's root changed identity while a
value was pushed), which meant visiting Favourites threw the loaded tracker away.
Selection has no such coupling, so trackers stay parsed in `MacUIState` and the
three pieces of state that existed only to work around the push shape
(`prepared`, `refreshedArtist`, `refreshToken`) are gone.

## MacRootView.swift::geometry-clamp — the detail column is size-clamped

`GeometryReader` clamps the detail column to the size it is offered. A tall
`LazyVGrid` reports an ideal height of the whole grid, so a tracker with ~40 eras
sized the whole `NavigationSplitView` to that and pushed BOTH columns up under
the titlebar — taking hover hit-testing with them, so row controls appeared on
the row below. Small trackers fit and looked fine, which is why it only showed up
on the big ones.

## LeakSheetApp.swift::window-scene — `Window`, not `WindowGroup`

The commands raise the main window by id (⌘I and ⌥⌘Q drive an inspector only
that window shows). `openWindow(id:)` on a `WindowGroup` opens ANOTHER instance
instead of bringing the existing one forward, which produced two identical main
windows. A `Window` scene is a singleton, and it also removes File ▸ New and
contributes its own Window-menu item, so the explicit
`CommandGroup(replacing: .newItem)` and hand-rolled menu items are unnecessary.

## LeakSheetCommands.swift::arrow-modifiers — ⌥⌘←/→ for previous/next

A menu key equivalent is matched before the first responder sees the event, so
binding the bare-⌘ arrows — the system's move-to-start/end-of-line shortcuts —
made them play tracks instead of moving the caret in the tracker URL field. This
is the same trap the file's own header records for bare `Space`; `MacSongList`
can safely bind Space because `onKeyPress` only fires while the list has focus.

## MacEraGrid.swift::tile-sizing — a clear square with the cover inside

`aspectRatio(1, contentMode: .fill)` on the cover has no definite size to work
from — `CachedImage` is already `.resizable().aspectRatio(.fill)`, so the pair
grew without bound and tiles painted over the header and out of the window. A
`Color.clear` square sized by the grid cell, with the cover drawn into it as an
overlay and clipped, bounds it.

## MacArtistView.swift::flat-modes — badge filters skip the grid

`isEraExpanded` returns true for EVERY era while a badge filter is active and
`toggleEra` is a no-op, so an era grid would be a dead end there. Search, the
badge filters and recents all render one flat cross-era list instead. Content
tabs carry `MiscEntry` values rather than songs, so they still render through the
shared `MiscListView` accordion.

## DesignTokens.swift::adaptive-palette — one dynamic-colour fork

SwiftUI has no cross-platform dynamic `Color` initialiser, so `Color.adaptive`
forks on AppKit/UIKit once and every token is built from it. `Color.tone`
derives each badge's light variant from the same hue rather than hand-authoring
30 second literals. Asset-catalog colour sets would also work, but the palette is
declared in HSB and the catalog would have to be kept in step by hand.

## DesignTokens.swift::scheme-parameter — contrast maths takes the scheme

`rgbComponents` used to hardcode `colorScheme = .dark`, which was honest while
the app forced dark. With an appearance-aware palette, resolving `.lsBackground`
in the wrong scheme hands the contrast maths the opposite backdrop and every
derived colour inverts. The scheme is a parameter now, defaulting to `.dark` so
the pinned literal tests keep their meaning.

## DesignTokens.swift::preferred-text-crossover — compare, don't split at 0.5

`preferredText` chose white below luminance 0.5 and black above. The WCAG
crossover is near 0.179, so every mid-tone backdrop in between got white text
where black reads better. It compares both candidates now.

## EraDisplayColors.swift::adaptive-dimming — dark dimming scales with the cover

The dark card is the cover colour multiplied down toward black. A fixed 0.55/0.40
was tuned on mid-dark covers; a near-white one landed the card in a mid-tone band
where white clears AA on neither gradient stop and black clears it on neither
either. The multiplier steps down for bright covers until the card is dark enough
to title in white, floored at 0.20 so a white cover keeps a hint of its own tone.
The title itself is chosen against the LIGHTER of the two real stops — deriving
it from a separate blend is what let a dark cover title itself white on a
near-white light-appearance card.

## Metrics.swift::input-device-metrics — 44pt is a finger, not a pointer

Touch platforms want the 44pt HIG hit target; a Mac driven by a pointer wants
roughly half that, and rows sized for a finger waste about a third of a desktop
window's vertical space. Forked once rather than at the ~15 call sites that would
otherwise each carry an `#if os(macOS)`.

## QueueSheet.swift::embedded-chrome — no navigation chrome in the inspector

The inspector sits OUTSIDE the detail column's navigation container, so
`navigationTitle`/`toolbar` there do not label the panel — they overwrite the
window's own title and drop Clear into the main toolbar. The embedded path
renders its count and Clear as an inline header instead.
