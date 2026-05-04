# LeakSheet — iOS App

Native SwiftUI client for [LeakSheet](../README.md). Browse trackers, stream audio, and manage favourites with full lock-screen and Now Playing integration.

## Stack

- **SwiftUI**, iOS 26+
- **Swift 6** (strict concurrency, `MainActor` default isolation)
- **Observation framework** (`@Observable`) for state
- **AVPlayer** + `MPNowPlayingInfoCenter` for playback
- **Liquid Glass** design language
- **Zero third-party dependencies**

## Setup

Requires **Xcode 26+** and an iOS 26+ device or simulator.

```bash
open LeakSheet.xcodeproj
```

By default the app talks to the FastAPI backend (see [root README](../README.md)). Update the base URL in `Services/APIClient.swift` if you're not using the default.

## Features

- 🔗 Tracker URL input with paste support and recent trackers
- 📚 Browse pre-indexed artists from `Artists.ndjson`
- 🔍 Debounced search with Best Of / Recents / No Snippets filter chips
- 🎨 Era cards with dominant-color gradients
- 🎵 Inline streaming with mini-player, full-screen Now Playing, and queue
- 🔒 Lock-screen controls + Control Center integration
- 👆 Swipe right to play, swipe left to queue, long-press for context menu
- ⭐ Favourites grouped by artist/era (UserDefaults persistence)
- 💾 Disk cache with ETag validation; in-memory image cache

## Project Layout

```
LeakSheet/
├── LeakSheetApp.swift
├── ContentView.swift
├── Models/         — Artist, Era, Song, SongVersion, StreamResolver
├── Services/       — APIClient, AudioEngine, CacheService, ImageCache (actors)
├── ViewModels/     — ArtistVM, PlayerVM, Favourites, RecentTrackers
├── Views/
│   ├── Landing/    — LandingView, TrackerInput, BrowseArtists
│   ├── Artist/     — ArtistView, EraCard, SongRow, VersionRow, …
│   ├── Player/     — MiniPlayerBar, NowPlayingView
│   └── Shared/     — CachedImage, SongDescriptionSheet, QueueSheet, …
└── Utilities/      — DesignTokens, EraColorExtractor, Haptics
```

For the full design spec, see [SPEC.md](SPEC.md).
