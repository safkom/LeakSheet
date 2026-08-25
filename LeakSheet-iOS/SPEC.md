# LeakSheet Apple apps — Specification

> Reference spec for the maintained native clients.
> Targets: SwiftUI, iOS 27 / macOS 27 / tvOS 27, Swift 6, Liquid Glass design language.
> Last verified against source: 2026-07-25 (iOS sections), 2026-08-03 (platform matrix).

---

## Platform matrix

One Xcode project, two app targets. `Shared/` (models, services, view models,
platform-neutral views) belongs to both; each platform owns its own view tree.

| | iOS | macOS | tvOS |
|---|---|---|---|
| Target | `LeakSheet` | `LeakSheet` | `LeakSheetTV` |
| Shell | `NavigationStack` | `NavigationSplitView`, selection-driven detail | sidebar `TabView` |
| Era browsing | accordion (`EraCardView`) | `LazyVGrid` of covers, drill-in | accordion |
| Song list | flattened `LazyVStack` | `List(selection:)` | focus list |
| Player bar | `safeAreaBar` | `safeAreaBar` (window bottom) | `safeAreaBar` |
| Song actions | swipe + context menu | hover controls, double-click, right-click | detail screen |
| Details | sheet | `.inspector` tab | detail screen |
| Refresh | `.refreshable` | ⌘R | toolbar button |
| Queue | sheet | `.inspector` tab (⌥⌘Q) | full-screen |
| Now Playing | sheet | separate `Window` (⇧⌘0) | full-screen |
| Settings | sheet | `Settings` scene (⌘,) | sidebar tab |
| Appearance | system | system | system |
| Web links | `SFSafariViewController` | `NSWorkspace` | QR code |
| Embeds | `WKWebView` | `WKWebView` (AppKit) | QR code — no WebKit on tvOS |
| Video | `AVPlayerLayer` + `AVPlayerViewController` | AVKit `VideoPlayer` | AVKit `VideoPlayer` |
| Audio session | `AVAudioSession` | none (CoreAudio) | `AVAudioSession` |
| Haptics | yes | no-op | no-op |
| Clipboard | `UIPasteboard` | `NSPasteboard` | unavailable |
| Sandbox | — | app sandbox + network client | — |

Liquid Glass (`glassEffect`, `GlassEffectContainer`, `buttonStyle(.glass)`,
`safeAreaBar`) is available on all three platforms and is used unchanged.

Platform divergence is confined to `Shared/Utilities/Platform.swift`,
`Shared/Utilities/Metrics.swift` (control metrics per input device), the
`#if os(macOS)` regions in `AudioEngine`/`LeakSheetApp`/`VideoSurfaceView`/
`EmbedPlayerView`/`SafariView`/`MiniPlayerBar`/`NowPlayingView`, two mid-chain
`#if`s in `ArtistView`, and the per-platform view folders.

macOS forks its own row and list views (`LeakSheet/Views/macOS/`) rather than
sharing the iOS ones: the iOS screen is an accordion driven by taps and swipes,
the Mac one a grid plus a selectable `List` driven by clicks, keys and hover.
They agree on `ArtistViewModel` — every filter, search and playback path is the
same code. Leaf views (`BadgePill`, `CreditTagsView`, `EraCardView`,
`ArtworkPlaceholder`) stay shared and read `Metrics`.
See [DECISIONS.md](DECISIONS.md).

---

## 0. Architecture

- **Language:** Swift 6 (strict concurrency)
- **UI:** SwiftUI, iOS 27+ / macOS 27+ / tvOS 27+
- **Build settings:** `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`, `SWIFT_APPROACHABLE_CONCURRENCY = YES`
- **Navigation:** `NavigationStack(path:)` with type-safe `.navigationDestination(for: Artist.self)`
- **State:** `@Observable` macro (Observation framework), `@Environment` injection
- **Services:** `actor`-isolated (`APIClient`, `CacheService`, `ImageCache`); `AudioEngine`
  is a `@MainActor @Observable` singleton (not an actor); `PlaybackQueueLogic` is a pure value type
- **Audio:** `@MainActor @Observable AudioEngine` singleton with AVPlayer
- **Models:** `nonisolated` Codable structs (opt out of default MainActor isolation)
- **Filter pipeline:** `nonisolated static` and pure — `FilterPipeline.swift`
  takes an `Artist` + `FilterState` and returns computed content; the view
  model holds only MainActor state
- **Dependencies:** Zero third-party

### File Structure (52 files)
```
LeakSheet/
├── LeakSheetApp.swift
├── ContentView.swift               # NavigationStack root; prepares the artist VM before pushing
├── Models/
│   ├── Models.swift                # Artist, Era, Section, Song, SongVersion, Badge, MiscEntry, TabSection…
│   └── StreamResolver.swift        # Streamable-link classification (host parity w/ src/streaming.py)
├── Services/
│   ├── APIClient.swift             # HTTP client actor (sheet, image-proxy, metadata, trackers)
│   ├── AudioEngine.swift           # @MainActor: AVPlayer + MPNowPlayingInfoCenter + video + queue
│   ├── CacheService.swift          # Disk cache actor with ETag validation (v2, SHA-256 keys)
│   ├── ImageCache.swift            # Actor: NSCache + URLCache + ImageIO downsample + prefetch
│   └── PlaybackQueueLogic.swift    # Pure value type: queue / era-rollover / list auto-advance
├── ViewModels/
│   ├── ArtistViewModel.swift       # MainActor state: chips, debounce, era rows, colors
│   ├── FilterPipeline.swift        # The pure off-main half: filter / search / recents / stats / dates
│   ├── PlayerViewModel.swift       # Thin @Observable façade over AudioEngine
│   ├── FavouritesManager.swift     # File-backed JSON persistence singleton
│   └── RecentTrackersManager.swift
├── Views/
│   ├── Landing/
│   │   ├── LandingView.swift
│   │   ├── TrackerInputView.swift
│   │   ├── BrowseArtistsView.swift     # Explore Trackers — GET /trackers (TrackerHub)
│   │   └── RecentTrackerCardView.swift
│   ├── Artist/
│   │   ├── ArtistView.swift            # Screen shell + ArtistContentView
│   │   ├── ArtistContentLists.swift    # Filters / search / eras / content tabs / recents branches
│   │   ├── ArtistRowViews.swift        # EraRowView, FilterChip, NoticeBannerView
│   │   ├── ArtistStatsBarView.swift
│   │   ├── EraCardView.swift           # Glass era card — used by the era list AND content tabs
│   │   ├── SongRowView.swift
│   │   ├── VersionRowView.swift
│   │   ├── BadgeRowView.swift
│   │   ├── CreditTagsView.swift        # feat / prod / with / ref / artist (credited_artists)
│   │   ├── MiscEntryRowView.swift      # Content-tab entry row
│   │   └── SongContextMenu.swift       # Shared context menu + 3-dot menu
│   ├── Player/
│   │   ├── MiniPlayerBar.swift
│   │   ├── NowPlayingView.swift        # Full-screen now-playing
│   │   └── VideoSurfaceView.swift      # Inline video at native aspect
│   └── Shared/
│       ├── CachedImage.swift           # ImageCache-backed image view
│       ├── BadgePill.swift             # BadgePill, DedupedBadgePills, ArtworkPlaceholder
│       ├── FlowLayout.swift            # Wrapping layout for pill rows
│       ├── SongDescriptionSheet.swift  # Full metadata sheet
│       ├── SongInfoSections.swift      # FileInfoSection / FileInfoRows / EvidenceSection
│       ├── TrackerStatsSheet.swift
│       ├── TrackerTimelineSheet.swift
│       ├── BadgeLegendSheet.swift
│       ├── QueueSheet.swift
│       ├── FavouritesView.swift
│       ├── EmbedPlayerView.swift       # Embedded web player fallback
│       ├── SafariView.swift            # SFSafariViewController wrapper
│       └── SettingsView.swift          # Backend URL, cache clear, autoplay, streaming mode
└── Utilities/
    ├── DesignTokens.swift        # Colors, BadgeVariant, CreditType, Format helpers
    ├── BadgeLogic.swift          # SPEC §12 badge dedupe rules
    ├── EraColorExtractor.swift   # Median-cut dominant color from cover art
    ├── EraDisplayColors.swift    # Derived readable era gradient/text colors
    ├── MiscLinkClassifier.swift  # Classifies misc links (video/archive/stream/embed)
    ├── TrackerURLNormalizer.swift
    └── Haptics.swift
```

---

## 1. Screens & Navigation Flow

```
ContentView (NavigationStack root)
  └── LandingView
       ├── TrackerInputView     — URL text field + paste + submit (Liquid Glass)
       ├── Browse Artists button — opens BrowseArtistsView sheet (Liquid Glass)
       ├── RecentTrackerCards   — recent trackers with cached art
       └── FavouritesView       — favourited songs grouped by artist/era

  → .navigationDestination(for: Artist.self) →

  ArtistView (system back gesture) — content on the first frame; its view model
  is built while the landing spinner is still up, so there is ONE loading state
  ├── NoticeBanner         — alert/info banners (not dismissible)
  ├── ArtistStatsBar       — total / available / snippets / full HQ
  ├── .searchable()        — debounced search with filter toggles (Liquid Glass)
  ├── FilterChips          — Best Of / Worst Of / Grails / Recents / No Snippets
  ├── Content tabs         — Released / Stems / Misc / Music Videos / Fakes …
  │                          (chips → pages; each page is EraCard accordions,
  │                          the same card the main era list uses)
  └── ScrollView
       └── LazyVStack of EraRows (flattened: card → section → song → version)
            ├── Cover art + gradient (dominant color)
            ├── Title + alt names + timeline
            ├── Collapsible description
            └── SongList
                 ├── Section headers (inline; the list is one flat LazyVStack,
                 │   so nothing is pinned)
                 └── SongRows
                      ├── Badge + title + version tag + badges + length
                      ├── Swipe right = play; swipe left = favourite, then queue
                      ├── Long-press = SongContextMenu
                      └── Expand → VersionRows
                           ├── BadgeRow (quality + availability)
                           └── CreditTags (feat/prod/collab/ref)

MiniPlayerBar (fixed bottom overlay, Liquid Glass)
  ├── CachedImage + track info + play/pause + progress line
  └── Tap → NowPlayingView sheet

NowPlayingView (sheet)
  ├── CachedImage album art
  ├── Track info + progress bar + seek
  ├── Play/pause + prev/next + quality toggle
  └── Queue button → QueueSheet

Sheets:
  ├── SongDescriptionSheet — full song/version metadata (CachedImage)
  ├── QueueSheet           — reorderable playback queue
  ├── BrowseArtistsView    — searchable TrackerHub list (GET /trackers)
  ├── FavouritesView       — all favourites
  └── SettingsView         — cache management, about
```

---

## 2. API Contract

**Production base URL:** `https://sheets.safko.eu/api`

### POST /api/sheet
```
Request:
  Content-Type: application/json
  If-None-Match: "<etag>"  (optional, for 304 fast path)
  Body: {
    "url": "https://docs.google.com/spreadsheets/d/.../htmlview",
    "artist_name": null,     // optional override
    "use_cache": true,
    "force_refresh": false
  }

Response 200:
  ETag: "<hash>"
  X-Cache-Status: "hit" | "stale" | "miss" | "validated"
  Cache-Control: public, max-age=300
  Body: Artist JSON (see Data Models)

Response 304 (Not Modified):
  ETag: "<hash>"
  X-Cache-Status: "validated"
  (no body)

Errors:
  400 — Invalid URL
  403 — Access denied (Google Sheets 403)
  404 — No table data found
  422 — Parse error (0 eras)
  502 — Network error (upstream unreachable)
```

### GET /api/image-proxy?url=...
```
Proxies images from Google CDN (CORS bypass).
Allowed domains: *.googleusercontent.com, *.ggpht.com, *.gstatic.com
Response: image/* with Cache-Control: public, max-age=86400
```

### GET /api/metadata?url=...
```
Fetches audio file metadata from provider APIs.
Providers: pillows (codec/bitrate/duration + HEAD fallback), froste (quality analysis),
imgur (file info), pixeldrain (file info). Every provider result carries `media_kind`
("audio" | "video" | "unknown") — the only video signal for opaque stream-host URLs.
Response: { provider, codec?, bitrate?, sample_rate?, duration?, ... }
Cached: max-age=3600
```

### GET /api/stream?url=...&download=false
```
Proxies audio stream from supported file hosts.
Hosts: pillows.su, pillowcase.su, imgur.gg, temp.imgur.gg, music.froste.lol, krakenfiles.com,
pixeldrain.com (`/u/{id}`), drive.google.com (`/file/d/{id}`, `open?id=`, `uc?id=`; the
virus-scan interstitial is retried via its confirm form — persistent interstitial → HTTP 409
`gdrive_interstitial`, private file → 403)
Supports HTTP Range requests (byte-range seeking).
MIME sniffing: magic-byte detection corrects misreported Content-Types.
Response: audio/* stream with Accept-Ranges: bytes
```

### POST /api/cache/clear
```
Clears server-side URL fetch cache.
Response: { "cleared": <count> }
```

---

## 3. Data Models

### Artist
```
name: String
slug: String                    // URL-safe identifier
source_url: String?
eras: [Era]
tracker_stats: TrackerStats?
parse_metadata: ParseMetadata?
notices: [Notice]
total_songs: Int (computed)     // sum of era song counts
total_versions: Int (computed)  // sum of era version counts
```

### Era
```
name: String
alt_names: [String]
description: String?
timeline: [TimelineEvent]
stats_raw: String?
stats: EraStats?
art_url: String?
highlighted_producers: [String]
sections: [Section]
songs: [Song] (computed)        // flat list across all sections
song_count: Int (computed)
version_count: Int (computed)
```

### Section
```
name: String                    // empty string for default section
group: String?                  // parent group label
songs: [Song]
```

### Song
```
base_name: String
song_key: String                // stable cross-era identity ("" for placeholders)
versions: [SongVersion]
badge: String? (computed)       // highest-precedence badge across versions:
                                // grail > best > special > wanted > worst > ai
```
> The server also emits `available_length` / `quality` / `track_length` /
> `leak_date` / `file_date` mirrors of the primary version. iOS does not decode
> them — rows read the version they actually display.

### SongVersion
```
name: String
version_tag: String?            // "V1", "V2", "Alt.", "Radio Mix", etc.
badge: String?                  // "best", "special", "worst", "grail", "wanted", "ai"
featuring: String?
producers: String?
collaboration: String?
refs: String?
credited_artists: String?      // performer from a dedicated Artist column (distinct from featuring)
alt_titles: [String]
notes: String?
og_filename: String?
samples: [String]
track_length: String?
file_date: String?
leak_date: String?
available_length: String?       // "Full", "Partial", "Snippet", "Confirmed", etc.
quality: String?                // "CD Quality", "High Quality", "OG File", etc.
streaming: Bool?                // Streaming Yes/No column (main tab)
rating: Int?                    // fan star rating 1-5 (Travis-style ⭐ suffix)
links: [String]
sources: [SourceRef]            // labeled evidence links (Sources column)
og_filenames: [String]          // all OG names; og_filename is the legacy first
date_of_recording: String?      // Carti-specific
type: String?                   // Carti-specific
```
> Credits parse from either bracket style — `(prod. X)` and `[prod. X]` — since
> the Travis tracker uses square brackets.

### Badge (String enum)
```
best     — ⭐ / 💎
special  — ✨
worst    — 🗑️
grail    — 🏆
wanted   — 🏅 / 🥇 / 🥉
ai       — 🤖
```

### EraStats / ParseMetadata (server-side only)
The tracker-declared per-era stats block and the parse diagnostics are still
emitted by the API (its own health harness reads them), but **iOS does not
decode either** — no screen shows them. Era counts on screen come from
`ArtistViewModel.computeEraStats`, which counts the parsed versions.

### TrackerStats
```
// Links
total_links, missing_links, sources_needed, not_available_links: Int
// Quality
lossless, cd_quality, high_quality, low_quality, recordings, not_available_quality: Int
// Availability
total_full, og_files, stem_bounces, full, tagged, partial, snippets, unavailable: Int
// Badges
best_of, special, grails, wanted, worst_of: Int
```
> iOS decodes everything above except `total_links`, `not_available_links` and
> `total_full`, which no screen renders.

### Notice
```
text: String
link: String?
kind: String                    // "alert" or "info"
```

### TimelineEvent
```
date: String
event: String
```

### DiscoveryArtist (BrowseArtistsView)
```
name: String
url: String
credit: String?
up_to_date: Bool?               // TrackerHub freshness flag
best: Bool?                     // recommended tracker
```
> `working_links` is also emitted; iOS does not decode it.

---

## 4. Audio Playback

### Stream Resolution (client-side)
All audio/video streams go through `/api/stream?url=<encoded_original_link>`.
Supported host patterns (per-host matchers in `Models/StreamResolver.swift` — kept in sync
with the backend resolvers in `src/streaming.py`; there is no single combined regex anymore):
- `pillows.su/f/{id}`, `pillowcase.su/f/{id}`
- `imgur.gg/f/{id}`, `temp.imgur.gg/f/{id}`
- `music.froste.lol/song/{hash}`
- `krakenfiles.com/view/{id}/file.html`
- `pixeldrain.com/u/{id}` (single files only — `/l/` lists open externally)
- `drive.google.com/file/d/{id}/…`, `open?id=`, `uc?id=`

A version with `og_filename` ending in a non-media extension (`.zip`, `.pdf`, …) is NOT
streamable; `MiscLinkClassifier` additionally reclassifies video/archive links on
streamable hosts.

### Original Quality URLs
- pillows: `https://api.pillows.su/api/download/{id}`
- froste: `https://music.froste.lol/song/{hash}/download`
- pixeldrain: `https://pixeldrain.com/api/file/{id}?download`
- imgur/kraken/gdrive: same URL (proxy serves original)

### Queue
- Max 200 items
- Each item: { id, version, artistName, eraName, artUrl }
- Auto-advance: queue first → era songs → stop
- Reorderable via drag
- Swipe-to-delete

### Background Audio
- AVAudioSession category: `.playback`
- MPNowPlayingInfoCenter: title (with badge emoji + version tag), artist, album (era name), artwork (proxied cover art)
- MPRemoteCommandCenter: play, pause, nextTrack, previousTrack (restart if >3s),
  changePlaybackPosition. skipForward / skipBackward are explicitly DISABLED so
  the lock screen shows track-skip controls rather than 15s jump buttons.
- UIBackgroundModes: `audio` only — the app schedules no background work

### Quality Switching
- Compressed stream (default) via `/api/stream`
- Original quality via direct download URL
- Preserves playback position on switch

---

## 5. Gestures & Interactions

| Element | Tap | Swipe Right | Swipe Left | Long Press |
|---------|-----|-------------|------------|------------|
| SongRow (single, streamable) | Play | Play | Add to queue | Context menu |
| SongRow (single, not streamable) | Show description | — | — | Context menu |
| SongRow (multi-version) | Expand/collapse | Play primary | Add primary to queue | Context menu |
| VersionRow (streamable) | Play | Play | Add to queue | Context menu |
| VersionRow (not streamable) | Show description | — | — | Context menu |
| EraCard header | Toggle expand | — | — | — |

### Context Menu Items (SongContextMenu.swift — shared)
1. Play (streamable versions only)
2. Add to Queue
3. Favourite / Unfavourite
4. Details

Used as both `.contextMenu` and `ThreeDotMenu` (ellipsis button) on SongRowView
and VersionRowView. Link actions (copy / open / download) live in the details
sheet, which lists every link with its own affordance.

### Haptic Feedback
`Haptics.light()` only — row taps, chip toggles, favourite toggles. Heavier
impact and notification styles were defined but never called.

---

## 6. Search & Filtering

### Search Scoring
Ranked tiers, highest first (`FilterPipeline.scoreSong`):

| Score | Match |
|---|---|
| 100 | base name equals the query |
| 90  | base name starts with the query |
| 70  | a word in the base name starts with the query |
| 60  | base name contains the query |
| 40  | an alt title contains the query |
| 20  | a credit (feat / prod / collab / ref) contains the query |
| 20  | notes contain the query |

A per-song lowercased haystack is precomputed off-main (`Precomputed.searchIndex`)
and is pinned by test to rank identically to the inline scorer.
Debounce: 200 ms via `Task.sleep`.

### Filter Toggles
- **Best Of:** keep versions badged best or special (`Badge.isBestOf`)
- **Worst Of:** keep versions badged worst
- **Grails:** keep versions badged grail or wanted
- **Recents:** every dated version, newest first — a sorted view, not a
  time-boxed window
- **No Snippets:** drop versions whose availability contains "snippet" or
  "unavailable", or whose quality is "not available" — applied per version
  (the same predicate filters misc entries)

Filtering is per **version**: a song survives if any of its versions do, and
the row then shows a badge belonging to the versions it kept.

---

## 7. Caching

### API Response Cache (CacheService v2)
- Store: URL → { data: raw Artist JSON bytes, etag, timestamp, artistName, slug,
  totalSongs, totalVersions, version } — SHA-256-derived file keys under
  Caches/LeakSheet/, schema-versioned (mismatched entries discarded on read)
- On request: send `If-None-Match: <etag>` → 304 means reopen the local copy
  (if the local copy is gone despite the 304, the entry is dropped and refetched)
- TTL: 7 days; multiple trackers cached concurrently; size reporting in Settings

### Favourites
- File-backed JSON at `Application Support/leaksheet/favourites.json`
  (the old UserDefaults key `leaksheet_favourites` is read once, to migrate)
- Writes are debounced and run off the main actor (`@concurrent`)
- Composite key: `{artistSlug}::{eraName}::{baseName}`

### Recent Trackers
- UserDefaults key `leaksheet_recent_trackers`, cap 20
- Each: { sourceUrl, artistName, slug, artUrl, totalSongs, totalVersions,
  availableCount, snippetCount, confirmedCount }
- Identity is the normalized URL, so one tracker never appears twice

### Images
- `ImageCache`: NSCache in memory (128 MB) over a 150 MB `URLCache` on disk
- Decoded through ImageIO at fixed pixel buckets [128, 320, 640, 1280, 1600]
- Era covers are **prefetched** for the whole tracker once the artist screen
  appears, so scrolling doesn't fetch per row
- Kept in preference to iOS 27's `AsyncImage` HTTP caching, which caches bytes
  but does no bucketed downsampling — bounding the bitmap is the point

### Era Colors
- In-memory dictionary + UserDefaults (`leaksheet_era_rgb_v3`, max 200 entries)
- Key: art_url → Value: dominant RGB

---

## 8. Design Tokens

### Colors (HSL → Swift Color)
```
Background:       #000000 (OLED black)
Card:             #0f0f0f
Card Hover:       #1a1a1a
Border:           #242424
Primary Blue:     HSL(220, 70%, 65%) → #5894f5
Primary Hover:    HSL(220, 60%, 58%) → #4a82e4
Foreground:       #e8e8e8
Muted:            #8c8c8c
Dim:              #595959
Player BG:        #080808
Error:            #f85149
Favourite:        #e84057
```

### Badge Colors (HSL)
```
OG Quality:    HSL(40, 90%, 55%)    — gold/amber
Lossless:      HSL(200, 85%, 68%)   — light blue
High Quality:  HSL(50, 92%, 58%)    — yellow
CD Quality:    HSL(130, 55%, 52%)   — green
Low Quality:   HSL(0, 75%, 62%)     — red
Not Available: HSL(0, 0%, 80%)      — light gray
OG File:       HSL(140, 60%, 50%)   — green
Full:          HSL(215, 75%, 65%)   — blue
Tagged:        HSL(150, 60%, 44%)   — dark green
Partial:       HSL(50, 92%, 58%)    — yellow
Snippet:       HSL(0, 75%, 62%)     — red
Confirmed:     HSL(0, 0%, 55%)      — gray
Beat Only:     HSL(275, 55%, 68%)   — purple
Stem:          HSL(270, 55%, 78%)   — light purple
```

### Typography
```
System (SF Pro) throughout, via semantic text styles only — no custom fonts
and no .rounded design. Weight carries hierarchy (.semibold / .bold titles).
Everything scales with Dynamic Type; pill rows use FlowLayout so they wrap
instead of clipping at accessibility sizes.
```

### Spacing & Radius
```
radius-sm:  6pt
radius-md:  10pt
radius-lg:  16pt
player-height: 72pt (mini), expandable
```

### Liquid Glass (iOS 27)
```swift
// Mini player bar — floating glass pill
.glassEffect(in: .rect(cornerRadius: 16))

// Tracker URL input — tinted when focused
.glassEffect(focused ? .regular.tint(.lsAccent) : .regular, in: .rect(cornerRadius: 12))

// Filter chips — tinted when active, interactive
.glassEffect(isActive ? .regular.tint(.lsAccent).interactive() : .regular.interactive())

// Search field in toolbar
.glassEffect(in: .rect(cornerRadius: 10))

// Browse Artists button — interactive glass
.glassEffect(.regular.interactive(), in: .rect(cornerRadius: 12))

// Navigation toolbar — automatic glass (no explicit .toolbarBackground)
```

Components using Liquid Glass:
- MiniPlayerBar (glass pill)
- TrackerInputView (tinted on focus)
- ArtistView FilterChip (tinted on active)
- ArtistView search field
- LandingView Browse Artists button
- ArtistView navigation toolbar (automatic)

---

## 9. Era Color Extraction

`EraColorExtractor` (actor) — a median-cut (ColorThief-style) reduction, not a
hue histogram:

1. Cover art is decoded by `ImageCache` at the 320 px bucket
2. Pixels are sampled and recursively split along their widest channel
3. The largest resulting bucket's mean RGB is the dominant color
4. Cached as RGB under `leaksheet_era_rgb_v3` in UserDefaults (max 200)

`EraDisplayColors.derive(from:)` then produces the card's palette by scaling
that RGB (title / body / border / gradient), and runs each result through the
WCAG contrast helpers so text stays legible on the tint it sits on. Extracted
colors are buffered and flushed once per frame — applying them per-card as they
land tripped SwiftUI's "glassEffect() tried to update multiple times per
frame" fault.

---

## 10. Animations

### Now-playing indicator
- SF Symbol with `.symbolEffect(.variableColor.iterative)`, gated on
  `accessibilityReduceMotion`

### Accordion Expand
- `withAnimation(.spring(duration: 0.3, bounce: 0.1))`, skipped under Reduce
  Motion
- The glass shape stays constant; the outer `clipShape` squares the card's
  bottom corners when expanded, so the glass effect itself never re-shapes

### Fade Transitions
- `.transition(.opacity)` for conditional content

---

## 11. Streaming Details

### Supported Hosts & Patterns
| Host | URL Pattern | Stream Resolution |
|------|-------------|-------------------|
| pillows.su | `/f/{id}` | → `/api/stream?url=...` (proxy) |
| pillowcase.su | `/f/{id}` | → `/api/stream?url=...` (proxy) |
| imgur.gg | `/f/{id}` | → `/api/stream?url=...` (proxy) |
| temp.imgur.gg | `/f/{id}` | → `/api/stream?url=...` (proxy) |
| music.froste.lol | `/song/{hash}` | → `/api/stream?url=...` (proxy) |
| krakenfiles.com | `/view/{id}/file.html` | → `/api/stream?url=...` (proxy) |
| pixeldrain.com | `/u/{id}` (single files) | → `/api/stream?url=...` (proxy) |
| drive.google.com | `/file/d/{id}`, `/open?id=`, `/uc?id=` | → `/api/stream?url=...` (proxy) |

### MIME Corrections (handled server-side)
- `audio/m4a` → `audio/mp4`
- `audio/x-m4a` → `audio/mp4`
- `application/octet-stream` → sniff magic bytes (OggS→ogg, fLaC→flac, ID3→mpeg, ftyp→mp4)

AVPlayer handles range requests natively — no client-side work needed.

---

## 12. Quality/Availability Badge Mapping

### Quality → Variant
```
contains "lossless" → lossless
contains "og"       → og
contains "cd"       → cd
contains "high"     → hq
contains "low"      → lq
contains "recording"→ rec
contains "beat"     → beatonly
else                → na
```

### Availability → Variant
> Also matched, beyond the table below: "rumo…" (covers both *Rumored* and the
> British *Rumoured*) and "conflicting" (Conflicting Sources) — both checked
> before "confirmed".
```
contains "og file"  → ogfile
equals "full"       → full
contains "tagged"   → tagged
contains "stem"     → stem
contains "beat"     → beatonly
contains "partial"  → partial
contains "snippet"  → snippet
contains "confirmed"→ confirmed
contains "unavailable" → unavailable
else                → na
```

### Display Logic
Implemented in `BadgeLogic` (Utilities) and rendered by `BadgePill` /
`DedupedBadgePills`; matches the web reference's `effectiveBadge` /
`getAvailBadge`.

**Primary pill**
1. Quality, when it says something — i.e. not empty, "Not Available" or "N/A"
2. Otherwise availability stands in (styled as availability)
3. If neither carries information, no pill

**Secondary availability pill** — shown only when *all* hold:
- a quality pill is showing, and
- availability differs from the quality text, and
- the value adds information: one of og file(s), full, tagged, stem /
  stem bounce(s), beat only, partial, snippet, confirmed, unavailable

Applied everywhere versions are listed: song rows, version rows, queue,
favourites, misc rows, and the details sheet (which renders the same decision
at a larger pill size).

---

## 13. Badge Emoji Map
```
best    → ⭐
special → ✨
worst   → 🗑️
grail   → 🏆
wanted  → 🏅
ai      → 🤖
```
