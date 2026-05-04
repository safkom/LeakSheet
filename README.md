# LeakSheet

A modern reader for tracker spreadsheets — turns clunky Google Docs trackers into a fast, browsable artist library with inline audio streaming.

Inspired by trackerhub.cx, built as a personal replacement while it's down.

> Made for fun with Claude Opus 4.6. Expect rough edges.

---

## What's in this repo

LeakSheet is split into three pieces:

| Piece | Path | Stack |
|---|---|---|
| **Backend / parser** | `src/` | Python 3.10+, FastAPI, httpx |
| **Web app** | `web/` | Vue 3, Vite, TailwindCSS, shadcn-ui — see [web/README.md](web/README.md) |
| **iOS app** | `LeakSheet-iOS/` | SwiftUI (iOS 26+), Swift 6 — see [LeakSheet-iOS/README.md](LeakSheet-iOS/README.md) |

Both apps talk to the same FastAPI backend.

### Web app (in short)

Browser-based tracker reader. Search and filter eras, stream audio inline, favourite songs, manage a queue, and switch between multiple trackers. Works on desktop and mobile.

### iOS app (in short)

Native SwiftUI client with Liquid Glass design, AVPlayer-based playback, lock-screen / Now Playing integration, swipe gestures, and offline disk caching with ETag validation.

---

## Features (backend + apps)

- 🎵 **Inline streaming** from pillows.su, imgur.gg, music.froste.lol, and krakenfiles.com
- 📊 **Live parsing** of Google Sheets trackers — no manual exports
- 🎨 **Per-era cover art colors** extracted on the fly
- 🔍 **Fast search & filters** across eras, songs, and versions
- ⭐ **Favourites & queue** persisted locally
- 📦 **ETag-aware caching** on both backend and clients

---

## Quick Start

You'll need Python 3.10+ and (for the web app) Node 18+.

```bash
# Backend
pip install -r requirements.txt
uvicorn src.api:app --reload          # → http://localhost:8000

# Web app (separate terminal)
cd web && npm install && npm run dev  # → http://localhost:5173
```

Then open the frontend and paste any supported tracker URL. For the iOS app, open `LeakSheet-iOS/LeakSheet.xcodeproj` in Xcode 26+ and run.

### One-liner: parse a tracker from the CLI

```bash
python -c "from src.fetcher import fetch_and_parse; a = fetch_and_parse('https://yetracker.net/'); print(f'{a.name}: {a.total_songs} songs')"
```

### Tests

```bash
python -m pytest tests/
```

---

## Supported Inputs

| Source | Example |
|---|---|
| Google Sheets htmlview | `docs.google.com/spreadsheets/d/{id}/htmlview` |
| Custom tracker domain | sites with embedded sheets (auto-redirected) |
| Links file | `Trackers/links.txt` — one URL per line |
| Local HTML export | `Trackers/.../sheet.html` (dev only) |

---

## Streaming Hosts

The backend proxies audio so clients can play it without CORS pain.

| Host | Link Format |
|---|---|
| pillows.su / pillowcase.su | `pillows.su/f/{id}` |
| imgur.gg / temp.imgur.gg | `temp.imgur.gg/f/{id}` |
| music.froste.lol | `music.froste.lol/song/{hash}` |
| krakenfiles.com | `krakenfiles.com/view/{id}/file.html` (CDN URL scraped) |

---

## API

```
POST /api/sheet              → Parse tracker URL → Artist JSON
GET  /api/stream?url=...     → Proxy audio from supported hosts
GET  /api/image-proxy?url=…  → Proxy images (CORS bypass)
GET  /api/metadata?url=...   → Audio file metadata
POST /api/cache/clear        → Clear URL fetch cache
```

---

## Data Model

```
Artist
└── Era (album / mixtape period)
    └── Section (optional sub-group, e.g. "Surfaced")
        └── Song (logical song, may have multiple versions)
            └── SongVersion (specific leak/recording with metadata)
```

---

## Backend Layout

```
src/
  models.py     — Pydantic data models
  parser.py     — HTML table → structured data
  fetcher.py    — URL fetching + disk cache
  streaming.py  — Audio stream resolution + proxying
  api.py        — FastAPI HTTP layer
  config.py     — Column aliases, paths
```

For deeper architecture notes, parsing strategy, and design decisions, see [agents.md](agents.md).

---

## CLI Tools

Useful when adding support for a new tracker layout:

| Tool | Purpose |
|---|---|
| `tests/tools/dump_raw_table.py` | Dump raw HTML table rows |
| `tests/tools/inspect_eras.py` | Show eras with song/version counts |
| `tests/tools/inspect_songs.py` | Inspect parsed songs with filters |
| `tests/tools/diff_trackers.py` | Compare column layouts across trackers |
| `tests/tools/debug_zero_eras.py` | Diagnose eras with 0 matched songs |

```bash
python -m tests.tools.inspect_eras --tracker ye
python -m tests.tools.inspect_songs --tracker ye --era "Yeezus 2"
```
