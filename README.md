# LeakSheet

Parser + API + web player for Google Spreadsheet-based music tracker documents. These spreadsheets catalog unreleased/leaked music from artists, organized into album/mixtape "eras."

## Quick Start

```bash
pip install -r requirements.txt

# Start the API server
uvicorn src.api:app --reload

# Start the web frontend (separate terminal)
cd web && npm install && npm run dev

# Parse a live Google Sheets URL
python -c "from src.fetcher import fetch_and_parse; a = fetch_and_parse('https://yetracker.net/'); print(f'{a.name}: {a.total_songs} songs')"

# Inspect with CLI tools
python -m tests.tools.inspect_eras --tracker ye
python -m tests.tools.inspect_songs --tracker ye --era "Yeezus 2"

# Run tests
python -m pytest tests/
```

## Architecture

```
src/
  models.py     — Pydantic data models (Artist, Era, Song, SongVersion, etc.)
  parser.py     — HTML table → structured data extraction
  fetcher.py    — Google Sheets URL fetching with file-based cache
  streaming.py  — Audio stream URL resolution + proxying (pillows.su, imgur.gg)
  api.py        — FastAPI HTTP layer with in-memory store
  config.py     — Column aliases, path management

web/
  src/
    composables/usePlayer.js       — HTML5 Audio playback with backend stream proxy
    composables/useApi.js          — API client wrapper
    composables/useUtils.js        — Badge/availability display helpers
    components/TrackerInput.vue    — Tracker URL input form with validation
    components/ArtistView.vue      — Artist detail view with search/filter
    components/EraCard.vue         — Collapsible era card with cover art colors
    components/SongList.vue        — Song list wrapper
    components/SongRow.vue         — Song display with streamable indicators
    components/VersionRow.vue      — Version display with play/equalizer animation
    components/PlayerBar.vue       — Progress bar, seek, volume, transport controls
    components/ContextMenu.vue     — Right-click context menu (copy link, download)
    components/SongDescriptionModal.vue — Detailed song/version info modal
```

## Input Sources

| Source | Example |
|--------|---------|
| Google Sheets htmlview | `docs.google.com/spreadsheets/d/{id}/htmlview` |
| Custom tracker domain | `yetracker.net` (redirects to htmlview) |
| Links file | `Trackers/links.txt` (one URL per line) |
| Local HTML export | `Trackers/Ye Tracker - Google Drive_files/sheet.html` |

> Production always uses live URLs. Local HTML files exist for offline development only.

## Data Hierarchy

```
Artist
  └── Era (album/mixtape period)
        └── Section (optional sub-group, e.g. "Surfaced")
              └── Song (logical song, may have multiple versions)
                    └── SongVersion (specific leak/recording with metadata)
```

## Audio Streaming

Songs with links to supported file hosts can be streamed directly in the web player.
The backend proxies audio to avoid CORS issues.

| Host | Link Format | API Endpoint |
|------|-------------|-----------|
| pillows.su / pillowcase.su | `pillows.su/f/{id}` | `api.pillows.su/api/get/{id}` |
| imgur.gg / temp.imgur.gg | `temp.imgur.gg/f/{id}` | `temp.imgur.gg/api/file/{id}/download` |
| music.froste.lol | `music.froste.lol/song/{hash}` | `music.froste.lol/song/{hash}/download` |

### API Endpoints

```
POST /api/sheet                      → Parse tracker URL → full Artist JSON
GET  /api/image-proxy?url=...        → Proxy images through backend (CORS bypass)
GET  /api/stream?url=...             → Proxy audio stream from supported hosts
POST /api/cache/clear                → Clear URL fetch cache
```

## Supported Trackers

| Artist | Live URL |
|--------|----------|
| Ye | `yetracker.net` |
| Kendrick Lamar | Google Sheets htmlview |
| Baby Keem | Google Sheets htmlview |
| Playboi Carti | Google Sheets htmlview |

## CLI Tools

| Tool | Purpose |
|------|---------|
| `tests/tools/dump_raw_table.py` | Dump raw HTML table rows |
| `tests/tools/inspect_eras.py` | Show eras with song/version counts |
| `tests/tools/inspect_songs.py` | Inspect parsed songs with filters |
| `tests/tools/diff_trackers.py` | Compare column layouts across trackers |
| `tests/tools/debug_zero_eras.py` | Diagnose eras with 0 matched songs |

## Architecture

See [agents.md](agents.md) for detailed architecture, data model, parsing strategy, and API design.