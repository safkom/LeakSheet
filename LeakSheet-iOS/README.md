# LeakSheet — Apple platform apps

Native SwiftUI clients for [LeakSheet](../README.md): **iOS 27**, **macOS 27** and
**tvOS 27**. Browse trackers, stream audio, and manage favourites with full
lock-screen / Now Playing integration.

One Xcode project, two app targets, one shared codebase.

## Stack

- **SwiftUI**, iOS 27+ / macOS 27+ / tvOS 27+
- **Swift 6** (strict concurrency, `MainActor` default isolation)
- **Observation framework** (`@Observable`) for state
- **AVPlayer** + `MPNowPlayingInfoCenter` for playback
- **Liquid Glass** design language — available on all three platforms
- **Zero third-party dependencies**

## Targets

| Target | Platforms | Folders |
|---|---|---|
| `LeakSheet` | iOS + macOS | `Shared/` + `LeakSheet/` |
| `LeakSheetTV` | tvOS | `Shared/` + `LeakSheetTV/` |
| `LeakSheetTests` | iOS + macOS | `LeakSheetTests/` |

`Shared/` holds everything that is not a platform's own view tree: models,
services, view models and the handful of presentational views that are
genuinely identical everywhere. It is a folder-synced group belonging to both
app targets.

> The shared code lives in its own root folder rather than inside `LeakSheet/`
> because a bare directory name in a folder-sync `membershipExceptions` list is
> silently ignored — excluding the iOS view tree from the tvOS target that way
> does not work. An explicit `Shared/` boundary is also easier to reason about.

## Setup

Requires **Xcode 27+**.

```bash
open LeakSheet.xcodeproj
```

The apps talk to the FastAPI backend (see [root README](../README.md)) at
`https://sheets.safko.eu/api` by default. To point elsewhere — a local
`uvicorn`, say — use **Settings → Backend URL** in the app; no code change
needed. All three platforms read the same `UserDefaults` key.

## Build and test

```bash
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcodebuild test -project LeakSheet.xcodeproj -scheme LeakSheet -destination 'platform=iOS Simulator,name=iPhone 17 Pro,OS=27.0'
```

```bash
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcodebuild test -project LeakSheet.xcodeproj -scheme LeakSheet -destination 'platform=macOS,arch=arm64'
```

```bash
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcodebuild -project LeakSheet.xcodeproj -scheme LeakSheetTV -destination 'platform=tvOS Simulator,name=Apple TV 4K (3rd generation),OS=27.0' build
```

Swift Testing (`import Testing`), 128 cases in `LeakSheetTests/`, all of which
run unchanged on both iOS and macOS. There is no tvOS test target — the code
under test is byte-identical and already covered twice. The schemes are shared,
so this all works from a clean clone.

## Features

Common to every platform:

- 🔗 Tracker URL input and recent trackers
- 📚 Browse artists from the live ArtistGrid feed (`GET /trackers`)
- 🗂️ Tab-mode chips: content tabs (Released / Stems / Misc / Music Videos / Fakes)
  render as pages of era cards; highlight tabs annotate songs with badges
- 🔍 Debounced search with Best Of / Worst Of / Grails / Recents / No Snippets chips
- 🎨 Era cards with dominant-colour gradients; covers prefetched per tracker
- 🎵 Streaming with a player bar, full Now Playing, and a queue
  (pillows, imgur.gg, froste, krakenfiles, pixeldrain, Google Drive)
- ⭐ Favourites grouped by artist/era (file-backed JSON in Application Support)
- 💾 CacheService v2 disk cache with ETag validation; bucketed image cache
- 🔒 System Now Playing integration (lock screen / Control Centre / Siri Remote)

Per platform:

| | iOS | macOS | tvOS |
|---|---|---|---|
| Shell | NavigationStack | NavigationSplitView sidebar | Sidebar TabView |
| Song actions | swipe + context menu | context menu + right-click | detail screen |
| Refresh | pull to refresh | ⌘R | toolbar button |
| Queue | sheet | inspector panel (⌥⌘Q) | full-screen |
| Now Playing | sheet | its own window (⇧⌘0) | full-screen |
| Web links | in-app Safari | default browser | QR code to continue on a phone |
| Embeds | WKWebView | WKWebView | QR code (no WebKit on tvOS) |
| Video | inline `AVPlayerLayer` + native fullscreen | AVKit `VideoPlayer` | AVKit `VideoPlayer` |
| Extras | haptics | menu bar commands, hover states | focus engine, Siri Remote play/pause |

## Project layout

```
Shared/                 — member of BOTH app targets
├── Models/             — Artist, Era, Song, SongVersion, Badge, StreamResolver, SongDetailPayload
├── Services/           — APIClient/CacheService/ImageCache (actors), AudioEngine (@MainActor), PlaybackQueueLogic
├── ViewModels/         — ArtistViewModel + FilterPipeline (pure, off-main), TrackerLoader,
│                         PlayerVM, Favourites, RecentTrackers
├── Utilities/          — DesignTokens, Platform (the whole shim surface), BadgeLogic,
│                         EraColorExtractor, Haptics, …
└── Views/              — BadgePill, BadgeRowView, CreditTagsView, CachedImage, FlowLayout

LeakSheet/              — iOS + macOS
├── LeakSheetApp.swift  — Scene body forks; macOS adds a Now Playing window and commands
├── ContentView.swift   — iOS NavigationStack root
├── Assets.xcassets
└── Views/
    ├── Landing/        — LandingView, TrackerInput, BrowseArtists, RecentTrackers*
    ├── Artist/         — ArtistView + ArtistContentLists + ArtistRowViews, EraCard, SongRow, …
    ├── Player/         — MiniPlayerBar, NowPlayingView, VideoSurfaceView
    ├── Shared/         — SongDescriptionSheet, Settings, Queue, Favourites, sheets
    └── macOS/          — MacRootView, LeakSheetCommands, MacUIState

LeakSheetTV/            — tvOS
├── LeakSheetTVApp.swift
├── Assets.xcassets     — its own catalog: tvOS needs layered brand assets
└── Views/              — TVRootView, TVBrowse/Recents/URLEntry/Favourites/Settings,
                          TVArtistView, TVSongRowView, TVSongDetailView, TVNowPlayingView,
                          TVQueueView, TVMiniPlayerBar, QRCodeSheet, TVInfoSheets

LeakSheetTests/         — Swift Testing suites (filter pipeline, queue logic, models, cache, colours, …)
Tools/make-icons.swift  — regenerates every app icon for all three platforms
```

## Icons

All app icons are generated, not hand-drawn:

```bash
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcrun swift Tools/make-icons.swift
```

Emits the iOS light/dark/tinted 1024s, the macOS `mac`-idiom sizes with the
standard inset and shadow, and the tvOS layered App Icon plus Top Shelf images.
It rewrites the `Contents.json` files too, so it is idempotent.

For the full design spec, see [SPEC.md](SPEC.md), and [DECISIONS.md](DECISIONS.md)
for the rationale log.
