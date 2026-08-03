# LeakSheet

A modern reader for tracker spreadsheets — turns clunky Google Docs trackers into a fast, browsable artist library with inline audio streaming.

Inspired by trackerhub.cx, built as a personal replacement while it's down.

> Made for fun with Claude Code. Expect rough edges.

---

## What's in this repo

LeakSheet is split into three pieces:

| Piece | Path | Stack |
|---|---|---|
| **Backend / parser** | `src/` | Python 3.10+, FastAPI, httpx, lxml |
| **Web app** | `web/` | Vue 3, Vite, TailwindCSS, shadcn-ui — see [web/README.md](web/README.md) · **unmaintained** |
| **Apple apps** | `LeakSheet-iOS/` | SwiftUI (iOS 27 / macOS 27 / tvOS 27), Swift 6 — see [LeakSheet-iOS/README.md](LeakSheet-iOS/README.md) |

All clients talk to the same FastAPI backend. The Apple apps are the maintained clients — one Xcode project builds iPhone/iPad, Mac and Apple TV from a shared codebase. The web app is kept for reference but no longer developed.

### Web app (in short)

Browser-based tracker reader. Search and filter eras, stream audio inline, favourite songs, manage a queue, and switch between multiple trackers. Works on desktop and mobile.

### iOS app (in short)

Native SwiftUI client with Liquid Glass design, AVPlayer-based playback, lock-screen / Now Playing integration, swipe gestures, and offline disk caching with ETag validation.

---

## Features (backend + apps)

- 🎵 **Inline streaming** from pillows.su, imgur.gg, music.froste.lol, krakenfiles.com, pixeldrain.com, and Google Drive
- 📊 **Live parsing** of Google Sheets trackers — no manual exports; secondary tabs (Released / Stems / Misc / Music Videos) become pages, highlight tabs (Best Of / Grails / Wanted / …) stamp badges
- 🗂️ **Tracker discovery** via the live ArtistGrid registry (`GET /trackers`)
- 🎨 **Per-era cover art colors** extracted on the fly
- 🔍 **Fast search & filters** across eras, songs, and versions
- ⭐ **Favourites & queue** persisted locally
- 📦 **ETag-aware caching** on both backend and clients (stale-while-revalidate)

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

Then open the frontend and paste any supported tracker URL. For the iOS app, open `LeakSheet-iOS/LeakSheet.xcodeproj` in Xcode 27+ and run (iOS 27+ device or simulator).

### One-liner: parse a tracker from the CLI

```bash
python -c "from src.fetcher import fetch_and_parse; a = fetch_and_parse('https://yetracker.net/'); print(f'{a.name}: {a.total_songs} songs')"
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest                  # offline gate: deterministic, no network, no local dumps needed
pytest -m accuracy      # exact-count regression vs local Trackers/ dumps (skips if absent)
pytest -m live          # fetches the locked live tracker set, drift-tolerant invariants
pytest -m "live and slow"  # full ArtistGrid sweep (deliberate, slow)
```

The suite is a marker-gated pyramid (`tests/unit|parse|fetch|api|live|accuracy`) with one
shared health definition in `tests/_health.py`. CI runs the offline gate on every push and a
soft live job daily (`.github/workflows/tests.yml`).

---

## Supported Inputs

| Source | Example |
|---|---|
| Google Sheets htmlview | `docs.google.com/spreadsheets/d/{id}/htmlview` (any `/edit`/`/view` form is normalized) |
| Custom tracker domain | sites with embedded sheets, e.g. `yetracker.net` |
| ArtistGrid registry | `GET /trackers` — live list of community trackers with up-to-date flags |
| Local HTML export | `Trackers/.../sheet.html` (dev only, gitignored) |

---

## Streaming Hosts

The backend proxies audio so clients can play it without CORS pain.

| Host | Link Format |
|---|---|
| pillows.su / pillowcase.su | `pillows.su/f/{id}` |
| imgur.gg / temp.imgur.gg | `temp.imgur.gg/f/{id}` |
| music.froste.lol | `music.froste.lol/song/{hash}` |
| krakenfiles.com | `krakenfiles.com/view/{id}/file.html` (CDN URL scraped) |
| pixeldrain.com | `pixeldrain.com/u/{id}` |
| drive.google.com | `drive.google.com/file/d/{id}/…` (virus-scan interstitial handled) |

---

## API

```
POST /api/sheet              → Parse tracker URL → Artist JSON (ETag / stale-while-revalidate)
GET  /api/trackers           → ArtistGrid discovery list (name, url, best, up-to-date flags)
GET  /api/stream?url=...     → Proxy audio/video from supported hosts (Range support)
GET  /api/image-proxy?url=…  → Proxy images (CORS bypass, width buckets, disk cache)
GET  /api/metadata?url=...   → File metadata from provider APIs (incl. media_kind)
POST /api/cache/clear        → Clear URL fetch cache (admin — requires X-Admin-Token: $LEAKSHEET_ADMIN_TOKEN)
```

### Environment variables

| Var | Default | Purpose |
|---|---|---|
| `LEAKSHEET_ADMIN_TOKEN` | *(unset)* | Shared secret required to call `POST /api/cache/clear`; unset ⇒ endpoint disabled (fail closed) |
| `LEAKSHEET_RATE_LIMIT_PER_MIN` | `0` (off) | Per-IP req/min cap on `/sheet`, `/stream`, `/image-proxy`, `/metadata` |
| `LEAKSHEET_TRUSTED_PROXY_HOPS` | `0` | Proxy hops to trust in `X-Forwarded-For`, counted from the right. Set this when enabling the rate limiter behind a router, or every caller shares one bucket |
| `LEAKSHEET_EXTRA_SHEET_HOSTS` | *(unset)* | Extra comma-separated hosts `/sheet` may fetch, on top of the built-in seed and the ArtistGrid feed |
| `LEAKSHEET_PREWARM` | `1` (on) | Hourly SWR-gap revalidation of actually-used trackers; `0` disables |
| `LEAKSHEET_PREWARM_INTERVAL` | `3600` | Seconds between prewarm passes |
| `LEAKSHEET_PREWARM_BATCH` | `25` | Max cache entries revalidated per prewarm pass |
| `LEAKSHEET_SHEET_CACHE_MAX_BYTES` | `1073741824` (1 GB) | Disk-cache size cap for fetched sheets/parses |

> The backend fetches URLs server-side, so every outbound path is guarded: `/sheet` only
> fetches allowlisted tracker hosts (built-in seed + the ArtistGrid feed +
> `LEAKSHEET_EXTRA_SHEET_HOSTS`), and the audio/image proxies re-validate the final host
> after redirects. Non-public addresses are rejected on every hop.

### Deployment

Self-hosted via Docker Compose (`docker-compose.yml`): an `api` container (`gunicorn` with a
single `UvicornWorker`, see `Dockerfile`) and a `web` container (`nginx` serving the built SPA
and reverse-proxying `/api/*` to `api` with the prefix stripped, see `web/Dockerfile` and
`web/nginx.conf`) — this replicates the same-origin `/api` routing the frontend and the
LeakSheet-iOS app both assume. `web` publishes port `8081` on the host; a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
(run separately, e.g. as a CasaOS app) points `sheets.safko.eu` at `http://localhost:8081`.

Single worker on purpose: the box can't fit two concurrent Ye-sized cold parses (11.7 MB HTML →
model tree + serialized dict each). CPU-bound parse/serialize work is pushed off the event loop
via `asyncio.to_thread`, so the single worker stays responsive during a cold miss.


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

Useful when adding support for a new tracker layout (debug scripts live in `scripts/tools/`;
the census harness stays importable under `tests/tools/`):

| Tool | Purpose |
|---|---|
| `tests/tools/census.py` | Per-tracker content census + gzipped live snapshots (accuracy baselines) |
| `scripts/tools/trackerhub_sweep.py` | Sweep every up-to-date ArtistGrid tracker: health, columns, tabs, date formats |
| `scripts/tools/verify_live.py` | Parse a live tracker and print a health summary |
| `scripts/tools/quick_inspect.py` | Quick parse output for the known local trackers |
| `scripts/tools/dump_raw_table.py` | Dump raw HTML table rows |
| `scripts/tools/inspect_eras.py` | Show eras with song/version counts |
| `scripts/tools/inspect_songs.py` | Inspect parsed songs with filters |
| `scripts/tools/diff_trackers.py` | Compare column layouts across trackers |
| `scripts/tools/analyze_structure.py` | Dump era-stats / global-stats / image structure of a live tracker |
| `scripts/tools/debug_zero_eras.py` / `deep_investigate.py` / `investigate_mismatch.py` | Row-level drill-downs for era-routing regressions |

```bash
python3 -m tests.tools.census --fixtures          # offline census of local dumps
python3 scripts/tools/trackerhub_sweep.py --limit 20
```