# LeakSheet

A modern reader for tracker spreadsheets — turns clunky Google Docs trackers into a fast, browsable artist library with inline audio streaming.

Inspired by trackerhub.cx, built as a personal replacement while it's down.

> Made for fun with Claude Code. Expect rough edges.

---

## What's in this repo

LeakSheet is split into three pieces:

| Piece | Path | Stack |
|---|---|---|
| **Backend / parser** | `src/` | Python 3.11+, FastAPI, httpx, lxml |
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

You'll need [uv](https://docs.astral.sh/uv/) and (for the web app) Node 18+. uv installs
Python 3.11 itself, from `.python-version`, so there is nothing else to set up.

```bash
# Backend
uv run uvicorn src.api:app --reload   # → http://localhost:8000

# Web app (separate terminal)
cd web && npm install && npm run dev  # → http://localhost:5173
```

Then open the frontend and paste any supported tracker URL. For the iOS app, open `LeakSheet-iOS/LeakSheet.xcodeproj` in Xcode 27+ and run (iOS 27+ device or simulator).

### One-liner: parse a tracker from the CLI

```bash
uv run python -c "from src.fetcher import fetch_and_parse; a = fetch_and_parse('https://yetracker.net/'); print(f'{a.name}: {a.total_songs} songs')"
```

### Tests

```bash
uv run pytest                  # offline gate: deterministic, no network, no local dumps needed
uv run pytest -m accuracy      # exact-count regression vs local Trackers/ dumps
uv run pytest -m live          # fetches the locked live tracker set, drift-tolerant invariants
uv run pytest -m "live and slow"  # full ArtistGrid sweep (deliberate, slow)
```

`-m accuracy` needs real tracker HTML under `Trackers/` and `.cache/`, which is never
committed — on a clean checkout those tests skip themselves and the command is a no-op.

Dependencies live in `pyproject.toml` and are pinned in `uv.lock`; `uv run` syncs the
environment before it runs anything. To change one, edit `pyproject.toml` then `uv lock`.

The suite is a marker-gated pyramid (`tests/unit|parse|fetch|api|quality|live`) with one
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
POST /api/sheet              → Parse tracker URL → Artist JSON (ETag / stale-while-revalidate;
                               Accept: application/x-ndjson streams progress lines on a cold parse)
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
| `LEAKSHEET_RATE_LIMIT_PER_MIN` | `0` (off) | Per-IP req/min cap on `/sheet`, `/stream`, `/metadata`; `/image-proxy` gets 10× this, since one screen loads dozens of covers. `/cache/clear` carries its own fixed cap of 10/min that applies whether or not this is set |
| `LEAKSHEET_TRUSTED_PROXY_HOPS` | `0` | Proxy hops to trust in `X-Forwarded-For`, counted from the right. Set this when enabling the rate limiter behind a router, or every caller shares one bucket |
| `LEAKSHEET_EXTRA_SHEET_HOSTS` | *(unset)* | Extra comma-separated hosts `/sheet` may fetch, on top of the built-in seed and the ArtistGrid feed. `/image-proxy` trusts only the seed plus this list — never the feed — so a feed-only tracker with self-hosted covers must be added here for its art to load |
| `LEAKSHEET_PREWARM` | `1` (on) | Hourly SWR-gap revalidation of actually-used trackers; `0` disables |
| `LEAKSHEET_PREWARM_INTERVAL` | `3600` | Seconds between prewarm passes |
| `LEAKSHEET_PREWARM_BATCH` | `25` | Max cache entries revalidated per prewarm pass |
| `LEAKSHEET_SHEET_CACHE_MAX_BYTES` | `1073741824` (1 GB) | Disk-cache size cap for fetched sheets/parses |
| `LEAKSHEET_GID_FETCH_CONCURRENCY` | `6` | Concurrent tab-page fetches across all requests. Each holds a full response body in memory |
| `LEAKSHEET_HUB_LOAD_CONCURRENCY` | `3` | Concurrent hub-workbook tab loads — fetched *and* parsed, so tighter than the above |
| `LEAKSHEET_IMAGE_RESIZE_CONCURRENCY` | `3` | Concurrent Pillow decodes in `/image-proxy`; each can hold a 15 MB input plus a 20 MP decode |

> The backend fetches URLs server-side, so every outbound path is guarded. `/sheet` only
> fetches allowlisted tracker hosts (built-in seed + the ArtistGrid feed +
> `LEAKSHEET_EXTRA_SHEET_HOSTS`), and that check covers every tab of a workbook, not just
> the URL it was handed — a sheet's own page-switcher JavaScript can name absolute tab
> URLs, which are honoured only for an allowlisted host or the sheet's own domain. The
> audio and image proxies re-validate the host they LAND on after redirects, not just the
> one they were given. Non-public addresses are rejected on every hop.

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
  config.py     — Column aliases, host allowlists, paths
  tracker_seed.py — Built-in tracker list served when ArtistGrid is unreachable
```

For why the non-obvious code looks the way it does, see [docs/decisions.md](docs/decisions.md) (backend) and [LeakSheet-iOS/DECISIONS.md](LeakSheet-iOS/DECISIONS.md) (Apple apps).

---

## CLI Tools

Useful when adding support for a new tracker layout (debug scripts live in `scripts/tools/`;
the census harness stays importable under `tests/tools/`):

| Tool | Purpose |
|---|---|
| `tests/tools/census.py` | Per-tracker content census + gzipped live snapshots (accuracy baselines) |
| `scripts/tools/trackerhub_sweep.py` | Sweep every up-to-date ArtistGrid tracker: health, columns, tabs, date formats |
| `scripts/tools/verify_live.py` | Parse a live tracker and print a health summary |
| `scripts/tools/dump_raw_table.py` | Dump raw HTML table rows |
| `scripts/tools/inspect_eras.py` | Show eras with song/version counts |
| `scripts/tools/inspect_songs.py` | Inspect parsed songs with filters |
| `scripts/tools/diff_trackers.py` | Compare column layouts across trackers |

```bash
uv run python -m tests.tools.census --fixtures    # offline census of local dumps
uv run python scripts/tools/trackerhub_sweep.py --limit 20
```