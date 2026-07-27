# LeakSheet — iOS App

Native SwiftUI client for [LeakSheet](../README.md). Browse trackers, stream audio, and manage favourites with full lock-screen and Now Playing integration.

## Stack

- **SwiftUI**, iOS 27+
- **Swift 6** (strict concurrency, `MainActor` default isolation)
- **Observation framework** (`@Observable`) for state
- **AVPlayer** + `MPNowPlayingInfoCenter` for playback
- **Liquid Glass** design language
- **Zero third-party dependencies**

## Setup

Requires **Xcode 27+** and an iOS 27+ device or simulator.

```bash
open LeakSheet.xcodeproj
```

The app talks to the FastAPI backend (see [root README](../README.md)) at
`https://sheets.safko.eu/api` by default. To point it elsewhere — a local
`uvicorn`, say — use **Settings → Backend URL** in the app; no code change
needed.

## Tests

```bash
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcodebuild test -project LeakSheet.xcodeproj -scheme LeakSheet -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

Swift Testing (`import Testing`), ~200 cases in `LeakSheetTests/`. The scheme is
shared, so this works from a clean clone.

## Features

- 🔗 Tracker URL input with paste support and recent trackers
- 📚 Browse artists from the live TrackerHub feed (`GET /trackers`)
- 🗂️ Tab-mode chips: content tabs (Released / Stems / Misc / Music Videos / Fakes)
  render as pages of era cards; highlight tabs annotate songs with badges
- 🔍 Debounced search with Best Of / Worst Of / Grails / Recents / No Snippets chips
- 🎨 Era cards with dominant-color gradients; covers prefetched per tracker
- 🎵 Inline streaming with mini-player, full-screen Now Playing, and queue
  (pillows, imgur.gg, froste, krakenfiles, pixeldrain, Google Drive)
- 🎬 Inline video at native aspect; tap → native fullscreen player
- 🔒 Lock-screen controls + Control Center integration
- 👆 Swipe right to play; swipe left to favourite or queue; long-press for the context menu
- ⭐ Favourites grouped by artist/era (file-backed JSON in Application Support)
- 💾 CacheService v2 disk cache with ETag validation; bucketed image cache

## Project Layout

```
LeakSheet/
├── LeakSheetApp.swift
├── ContentView.swift   — NavigationStack root; prepares the artist VM before pushing
├── Models/             — Artist, Era, Song, SongVersion, Badge, StreamResolver
├── Services/           — APIClient/CacheService/ImageCache (actors), AudioEngine (@MainActor), PlaybackQueueLogic
├── ViewModels/         — ArtistViewModel (MainActor state) + FilterPipeline (pure, off-main),
│                         PlayerVM, Favourites, RecentTrackers
├── Views/
│   ├── Landing/        — LandingView, TrackerInput, BrowseArtists, RecentTrackerCard
│   ├── Artist/         — ArtistView + ArtistContentLists + ArtistRowViews, EraCard, SongRow, …
│   ├── Player/         — MiniPlayerBar, NowPlayingView, VideoSurfaceView
│   └── Shared/         — CachedImage, BadgePill, FlowLayout, SongDescriptionSheet, sheets
└── Utilities/          — DesignTokens, BadgeLogic, EraColorExtractor, Haptics, …

LeakSheetTests/         — Swift Testing suites (filter pipeline, queue logic, models, cache, …)
```

For the full design spec, see [SPEC.md](SPEC.md).
