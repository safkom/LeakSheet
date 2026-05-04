# LeakSheet — Web App

Vue 3 frontend for [LeakSheet](../README.md). A fast, keyboard-friendly tracker browser with inline audio streaming, search, and favourites.

## Stack

- **Vue 3** + TypeScript + Vite
- **TailwindCSS v4** + shadcn-ui (reka-ui)
- **TanStack Virtual** for large song lists
- **ColorThief** for per-era cover art colors
- **IndexedDB** local cache (with ETag revalidation)

## Setup

```bash
npm install
npm run dev      # Dev server at http://localhost:5173 (proxies /api → :8000)
npm run build    # Production build
npm run preview  # Preview production build
```

The dev server proxies `/api` to `http://localhost:8000` — start the FastAPI backend (see [root README](../README.md)) alongside it.

## Features

- 🔗 Tracker URL input with validation and multi-tracker history
- 🔍 Real-time search/filter across eras, songs, and versions
- 🎨 Era cards with cover art color extraction
- 🎵 Audio streaming via backend proxy (pillows.su, imgur.gg, froste.lol, krakenfiles)
- 🎚️ Player bar with seek, volume, buffering indicators, and queue
- ⭐ Favourites, persisted locally
- 📋 Right-click / long-press context menu (play, queue, copy link, download)
- 📝 Song description modal with credits, samples, and external links
- ⌨️ Keyboard shortcuts: <kbd>Space</kbd> play/pause · <kbd>←</kbd>/<kbd>→</kbd> seek · <kbd>↑</kbd>/<kbd>↓</kbd> volume

## Project Layout

```
src/
  App.vue                — root, history, keyboard shortcuts
  composables/           — player, API client, filtering, colors, favourites, …
  components/            — ArtistView, EraCard, SongRow, PlayerBar, QueuePanel, …
  components/ui/         — shadcn / reka-ui primitives
```

See the [root README](../README.md) for the backend API and supported streaming hosts.
