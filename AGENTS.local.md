# LeakSheet — agents.md

## Project Overview

**LeakSheet** is a parser + API for Google Spreadsheet-based music tracker documents. These spreadsheets catalog unreleased/leaked music from artists, organized into album/mixtape "eras." Each era contains song entries with metadata about leaked versions.

Supports two input modes:
1. **Local HTML exports** — saved Google Sheets `_files/sheet.html` in `Trackers/` *(development reference only)*
2. **Live URLs** — Google Sheets `/htmlview` links or custom tracker domains (e.g. `yetracker.net`) *(primary / production mode)*

> **Important:** Always use live URLs for parsing. Local HTML files are for offline development reference only. The production API exclusively uses URL-based fetching via `fetcher.py`.

---

## Architecture

```
LeakSheet/
├── agents.md                  # This file — project plan
├── README.md
├── Trackers/
│   ├── links.txt              # Live tracker URLs (one per line)
│   └── *_files/sheet.html     # Local HTML exports (git-ignored in prod)
├── src/
│   ├── __init__.py
│   ├── models.py              # Pydantic data classes: Artist, Era, Song, SongVersion
│   ├── parser.py              # HTML → structured data extraction
│   ├── fetcher.py             # URL fetching: Google Sheets htmlview + custom domains
│   ├── streaming.py           # Audio stream URL resolution + proxying
│   ├── api.py                 # FastAPI endpoints (including /api/stream proxy)
│   ├── config.py              # Configuration, path management, column aliases
│   └── tracker_seed.py        # Fallback /trackers list when ArtistGrid is unreachable
├── web/                       # Vue 3 web client — UNMAINTAINED (see web/README.md).
│   └── src/{composables,components}/   # Kept for reference; does NOT track new backend
│                              # features (tabs, pixeldrain/GDrive, media_kind). The iOS
│                              # app is the maintained client — build new work there.
├── tests/                     # Marker-gated pyramid (2026-07 rebuild)
│   ├── conftest.py            # Cache isolation, mock-workbook httpx transport, TestClient
│   ├── _health.py             # THE single parse-health definition (strict + live-relaxed)
│   ├── unit/                  # Pure helpers: parser/models/fetcher/streaming/api units
│   ├── parse/                 # Real parse_sheet over committed synthetic fixtures + iOS contract
│   ├── fetch/                 # Real async_fetch_and_parse via httpx.MockTransport (tab selection)
│   ├── api/                   # TestClient contracts: /sheet /stream /metadata /image-proxy /trackers
│   ├── live/                  # -m live: locked URL set + ArtistGrid mass sweep (slow)
│   ├── quality/               # -m accuracy: invariants + hand-labelled ground truth (labels/*.json)
│   ├── fixtures/synthetic/    # DMCA-safe invented-content tracker HTML (committed)
│   ├── live_trackers.txt      # Locked public URL set for -m live
│   └── tools/                 # census.py (reads live_trackers.txt) + corpus_sweep.py
├── scripts/tools/             # One-off debug scripts (not collected by pytest)
│   └── trackerhub_sweep.py    # Sweep every ArtistGrid tracker (health/columns/tabs/dates)
├── docs/decisions.md          # Why non-obvious code is the way it is, keyed file.py::symbol
├── LeakSheet-iOS/
│   ├── SPEC.md                     # Full iOS app specification
│   ├── DECISIONS.md                # iOS counterpart of docs/decisions.md
│   ├── Shared/                     # Compiled into all three targets
│   │   ├── Models/                 # nonisolated Codable structs (Artist, Era, Song, etc.)
│   │   ├── Services/               # actors: APIClient, CacheService, ImageCache · @MainActor: AudioEngine · value type: PlaybackQueueLogic
│   │   ├── ViewModels/             # @Observable: ArtistViewModel, PlayerViewModel, FavouritesManager, RecentTrackersManager, TrackerLoader, FilterPipeline
│   │   ├── Views/                  # CachedImage, BadgeRowView
│   │   └── Utilities/              # DesignTokens, EraColorExtractor, EraDisplayColors, MiscLinkClassifier, TrackerURLNormalizer, Haptics, Platform
│   ├── LeakSheet/                  # iOS + macOS target
│   │   ├── ContentView.swift       # NavigationStack root (iOS)
│   │   └── Views/
│   │       ├── Landing/            # LandingView, TrackerInputView, BrowseArtistsView, RecentTrackerCardView
│   │       ├── Artist/             # ArtistView, EraCardView, SongRowView, VersionRowView, MiscEntryRowView, SongContextMenu, etc.
│   │       ├── Player/             # MiniPlayerBar, NowPlayingView, VideoSurfaceView
│   │       ├── Shared/             # SongDescriptionSheet, QueueSheet, FavouritesView, SettingsView, SafariView, EmbedPlayerView
│   │       └── macOS/              # Sidebar-selection Mac shell (MacRootView, MacArtistView, MacSongList, …)
│   ├── LeakSheetTV/                # tvOS target
│   └── LeakSheetTests/             # Swift Testing
├── pyproject.toml                  # Dependencies (locked in uv.lock), pytest + ruff config
└── uv.lock
```

---

## Data Model

### Hierarchy

```
Artist
  └── Era (album/mixtape period)
        └── Song (logical song, may have multiple versions)
              └── SongVersion (specific version with metadata)
```

### SongVersion Attributes (all optional except name)

| Field              | Type       | Notes                                      |
|--------------------|------------|--------------------------------------------|
| name               | str        | Display name including version tag [V1] etc |
| version_tag        | str?       | Extracted tag: "V1", "V2", "Alt." etc      |
| badge              | Badge?     | Emoji badge classification                 |
| featuring          | str?       | Featured artists, e.g. "Rhymefest"         |
| producers          | str?       | Producers, e.g. "Kanye West & Andy C."     |
| collaboration      | str?       | Collaboration artist, e.g. "Go Getters"    |
| refs               | str?       | Reference track by, e.g. "Keith Lawson"    |
| director           | str?       | Director credit on video rows, e.g. "Dave Meyers" |
| alt_titles         | list[str]  | Alternative song titles                    |
| notes              | str?       | Description/history text                   |
| og_filename        | str?       | Original filename from metadata            |
| samples            | list[str]  | Sampled songs/works                        |
| track_length       | str?       | Duration string, e.g. "3:14", "?:??"      |
| file_date          | str?       | Date the file was created/bounced          |
| leak_date          | str?       | Date the version leaked                    |
| available_length   | str?       | Full / Partial / Snippet / Confirmed / etc |
| quality            | str?       | CD Quality / High Quality / Recording / etc|
| streaming          | bool?      | Streaming Yes/No (main-tab Streaming column) |
| rating             | int?       | Fan star rating 1-5 (Travis-style ⭐ suffix) |
| links              | list[str]  | One or more URLs (links + alt-links + note links, merged) |
| sources            | list[SourceRef] | Labeled evidence links from a Sources column |
| og_filenames       | list[str]  | All OG filenames (notes convention + File Name column) |
| credited_artists   | str?       | Performer(s) from a dedicated Artist column (not a feature) |
| date_of_recording  | str?       | Recording date (Date of Recording / Record Date columns) |
| type               | str?       | Song type column                           |

Song also carries `song_key` — a normalized identity key for cross-era version linkage.

### Song Attributes

| Field      | Type             | Notes                                        |
|------------|------------------|----------------------------------------------|
| base_name  | str              | Song name without version tags/badges        |
| versions   | list[SongVersion]| All versions of this song                    |
| badge      | Badge? (property)| Badge from any version (computed)            |
| primary    | SongVersion? (property) | First/primary version (computed)      |

### Badge Enum (emoji badges, exactly one or none per song)

| Badge   | Emoji         | Meaning    |
|---------|---------------|------------|
| best    | ⭐/⭐️/💎      | Best of    |
| special | ✨             | Special    |
| worst   | 🗑️            | Worst of   |
| grail   | 🏆            | Grail      |
| wanted  | 🏅/🥇/🥉      | Wanted     |
| ai      | 🤖            | AI-generated |

Badges are per-version (attached to whichever version carries the emoji), but semantically represent the song.

### Era Attributes

| Field                  | Type              | Notes                                        |
|------------------------|-------------------|----------------------------------------------|
| name                   | str               | Full era name from header cell               |
| alt_names              | list[str]         | Alternative era names for matching           |
| description            | str?              | Historical context paragraph                 |
| timeline               | list[TimelineEvent] | Historical timeline (date + event)         |
| stats_raw              | str?              | Raw stats string (e.g. "3 OG File(s)...")    |
| stats                  | EraStats?         | Parsed stats (see below)                     |
| art_url                | str?              | Cover art image URL                          |
| highlighted_producers  | list[str]         | Notable producers for this era               |
| sections               | list[Section]     | Sub-sections (see below)                     |
| songs                  | list[Song] (property) | Flat list across all sections (computed) |
| song_count             | int (property)    | Total songs (computed)                       |
| version_count          | int (property)    | Total versions across songs (computed)       |

### Section Attributes

| Field  | Type       | Notes                                        |
|--------|------------|----------------------------------------------|
| name   | str        | Section name (e.g. "Surfaced", "Early Sessions") |
| group  | str?       | Parent group label (from consolidated sections) |
| songs  | list[Song] | Songs in this section                        |

### EraStats Attributes

| Field         | Type | Notes                                        |
|---------------|------|----------------------------------------------|
| og_files      | int  | Count of OG files                            |
| full          | int  | Full-length available                        |
| tagged        | int  | Tagged versions                              |
| partial       | int  | Partial versions                             |
| snippets      | int  | Snippet-only versions                        |
| stem_bounces  | int  | Stem bounces                                 |
| unavailable   | int  | Unavailable tracks                           |
| total         | int (property) | Sum of all categories (computed)     |

### TrackerStats Attributes

Global statistics parsed from the tracker header area. Groups:

- **Links:** `total_links`, `missing_links`, `sources_needed`, `not_available_links`
- **Quality:** `lossless`, `cd_quality`, `high_quality`, `low_quality`, `recordings`, `not_available_quality`
- **Availability:** `total_full`, `og_files`, `stem_bounces`, `full`, `tagged`, `partial`, `snippets`, `unavailable`
- **Badges:** `best_of`, `special`, `grails`, `wanted`, `worst_of`

### ParseMetadata Attributes

Diagnostic info about the parsing run:

| Field                | Type       | Notes                                   |
|----------------------|------------|-----------------------------------------|
| total_rows           | int        | Total non-header rows processed         |
| song_rows            | int        | Rows matched as songs                   |
| skipped_rows         | int        | Rows that matched nothing (data loss)   |
| unmatched_rows       | list[str]  | First 50 summaries of unmatched rows    |
| unmatched_rows_total | int        | Uncapped unmatched count                |
| footer_rows          | int        | Rows classified as footer content       |
| other_rows           | int        | Structural rows (era headers, section labels) — completes the identity `total == song + skipped + footer + other` |
| fuzzy_matched_rows   | int        | Rows matched via fuzzy era matching     |
| dropped_columns      | list[str]  | Non-empty header cells matching no alias (a whole column silently lost) |

### Artist Attributes

| Field           | Type            | Notes                                   |
|-----------------|-----------------|------------------------------------------|
| name            | str             | Artist display name                      |
| slug            | str             | URL-safe identifier (auto-generated)     |
| source_url      | str?            | Original Google Sheets / tracker URL     |
| eras            | list[Era]       | All eras for the artist                  |
| tracker_stats   | TrackerStats?   | Global stats from tracker footer         |
| parse_metadata  | ParseMetadata?  | Diagnostic info about the parse run      |
| notices         | list[Notice]    | Header announcements (kind: info/alert)  |
| misc_entries    | list[MiscEntry] | Rows from Misc / Music Videos tabs       |
| tabs            | list[TabSection]| Content-tab pages (Released/Streaming/Stems/Fakes/…) — badge tabs (Best Of/Worst Of/Special/Grails/Wanted) are NOT pages, they stamp badges onto main-tab songs, resolved per row (row emoji → `MiscEntry.section` label → tab kind) |
| total_songs     | int (property)  | Sum of all era song counts (computed)    |
| total_versions  | int (property)  | Sum of all era version counts (computed) |

---

## Parsing Strategy

### Column Detection

Trackers vary in column layout. The parser scans up to the first 11 rows for a header row
yielding ≥2 canonical column matches, then builds a column-index map via `COLUMN_ALIASES`
normalization (lowercase, parenthetical strip, **trailing-colon strip**, internal-whitespace
collapse). Includes prefix-matching fallback for headers with appended text (e.g. Carti's
"NotesWelcome to..."). Header cells matching no alias are surfaced in
`parse_metadata.dropped_columns` instead of failing silently. When two columns map to the same
canonical field, the first wins (the duplicate is reported as dropped).

| Tracker        | Columns                                                              |
|----------------|----------------------------------------------------------------------|
| Baby Keem      | Era, Name, Notes, Track Length, File Date, Leak Date, Avail Length, Quality, Link(s) |
| Kendrick Lamar | Era, Name, Notes, Track Length, File Date, Leak Date, Avail Length, Quality, Link(s) |
| Ye             | Era, Name, Notes, Track Length, File Date, Leak Date, Avail Length, Quality, Link(s) |
| Playboi Carti  | Era, Name, Notes, Track Length, Leak Date, Type, Avail Length, Quality, Links (dropped its "Date of Recording" column 2026-07) |
| Travis Scott   | Era, Title, Notes, What's Available? (compound: availability + HQ/LQ + ⭐ rating), Sources, Link(s) |
| SosMula-style  | Track Titles:, Artists:, Producers:, Release/Leaked Date:, links — colon-suffixed, era-less |

> **Note:** Some trackers use "Portion" instead of "Available Length". Both are recognized via `COLUMN_ALIASES`.

### Row Classification (in evaluation order)

1. **Header row(s)**: title/instruction rows before the detected column-header row are notice
   candidates; the header row itself sets the column map.
2. **Era header row**: first cell matches `ERA_STATS_PATTERN` and some cell carries a
   non-stats era name (digit-leading names like "38 Baby 2 [V1] / …" are accepted; pure
   numbers and stats-keyword lines are not). Checked **before** section separators — a
   genuine separator never carries era stats in col 0.
3. **Section label row**: known separator keywords (40+) or a structurally-detected short
   label → named `Section` in the current era.
4. **Footer row**: keyword-detected; a later era header resets footer state.
5. **Song row**: era-column value resolved to an era (tiers below). Rows with an empty era
   column fall back positionally to the current era.
6. **Empty/irrelevant rows**: skipped and counted (`skipped_rows` + `unmatched_rows`).

### Era-Song Matching (tiered; 2026-07-20 review)

Resolution order for a row's era value:
1. **Positional-exact prior** — if the value names ANY key form of the *current* header
   (`_era_own_keys`: primary/full/alt names, slash parts, comma-alias parts), it belongs
   there. This is what keeps sibling eras sharing a stripped key ("Fre3$tyle [V2]"/"[V3]",
   "38 Baby 2 [V1] / …") from stealing each other's bare rows.
2. **Exact** lookup (normalized, then version-tag-stripped) in the primary key dict —
   earlier genuine era headers win primary keys.
3. **Fallback dict** — slash parts, comma-alias parts, section-label aliases, and learned
   row-era variants; consulted only after primary misses so a genuine era declared later
   still claims its key.
4. **Positional fuzzy prior** — fuzzy match against the current header only; a first match
   registers the abbreviation in the fallback dict so repeats resolve exactly.
5. **Global fuzzy** (`_fuzzy_era_match`) — word-overlap ≥2 shared words + ≥50% of the smaller
   set, plus acronym matching.

When touching any of this, verify song **placement** (era → song lists), not just totals —
the accuracy suite pins counts, and `tests/unit/test_parser_units.py` pins the routing rules.

### Song Name Parsing

The Name field contains embedded info:
- **Version tag**: `[V1]`, `[V2]`, `[V2-V25]`, `[Alt.]`, `[Radio Mix]`
- **Badge emoji**: Leading `⭐`, `✨`, `🗑️`, `🏆`, `🏅`, `🥇`
- **Sub-info in parens**: `(feat. X)`, `(prod. Y)`, `(Alternative Title)`
- **Featured artist prefix**: `"Kendrick Lamar - "` means it's another artist's song featuring the tracker's artist

Songs with the same base name (minus version tags) are grouped as versions of one `Song` object.

### Link Extraction

Links in the HTML are `<a href="...">` tags. Google redirect wrappers (`google.com/url?q=REAL_URL`) are stripped to get the real URL.

---

## URL Fetching (`fetcher.py`)

### Supported URL Formats

| Format | Example | Handling |
|--------|---------|----------|
| Google Sheets htmlview | `docs.google.com/spreadsheets/d/{id}/htmlview` | Fetch HTML, extract `<table>` |
| Custom tracker domain | `yetracker.net` | Fetch page, find embedded sheet or direct table |
| Local file path | `Trackers/Ye Tracker - ..._files/sheet.html` | Read directly |

### Artist Name Detection

For URLs, artist name is inferred from the page `<title>` or sheet header. Can be overridden via API parameter.

---

## API Design (FastAPI)

### Endpoints

```
POST /api/sheet                      → Parse tracker URL → full Artist JSON (body: {url, artist_name?, use_cache?, force_refresh?})
GET  /api/trackers                   → ArtistGrid discovery list (name, url, credit, best, up_to_date, working_links)
GET  /api/image-proxy?url=...&w=...  → Proxy images (CORS bypass; width buckets 128–1600, disk-cached resizes)
GET  /api/metadata?url=...           → File metadata from provider APIs (pillows/froste/imgur/pixeldrain, incl. media_kind)
GET  /api/stream?url=...             → Proxy audio/video from supported hosts (Range support; gdrive interstitial → 409)
POST /api/cache/clear                → Clear the URL fetch cache (admin: X-Admin-Token == LEAKSHEET_ADMIN_TOKEN; disabled when unset)
```

### Caching

- **ETag-based validation**: `POST /api/sheet` returns an ETag header. Clients can send `If-None-Match` to get a `304 Not Modified` fast path.
- **Stale-while-revalidate**: Serves stale cache (up to 24h) immediately while triggering background refresh.
- **X-Cache-Status header**: Returns `hit`, `stale`, `miss`, or `validated` to indicate cache state.
- **Disk cache TTL**: 1-hour default, 24-hour max stale age.

### Error Responses

| Exception | HTTP Status | When |
|-----------|-------------|------|
| InvalidURLError | 400 | Malformed tracker URL |
| AccessDeniedError | 403 | Google Sheets returns HTTP 403 |
| NoTablesError | 404 | No `<table>` elements found in page |
| ParseError | 422 | Parsing produced 0 eras |
| NetworkError | 502 | Upstream unreachable or timeout |

### Data Loading

The API is stateless — each `POST /api/sheet` request fetches, parses and returns the full Artist JSON. Results are cached on disk (file-based, 1-hour TTL) to avoid repeated upstream fetches.

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| models.py | ✅ | Pydantic models incl. song_key, sources, rating, credited_artists, misc_entries, notices, TabSection |
| config.py | ✅ | Column aliases (sweep-driven vocabulary, user-confirmed mappings), TrackerHub URL, /sheet host allowlist |
| parser.py | ✅ | lxml fast path, tiered era matching w/ positional priors, badge tabs, misc/art/TrackerHub tab parsing |
| fetcher.py | ✅ | Async fetch, tab discovery/prioritization, hub-workbook aggregation, secondary-tab loading, file cache (SWR + ETag), sheet-host allowlist + `PublicOnlyAsyncTransport` |
| streaming.py | ✅ | pillows, imgur, froste, kraken, pixeldrain, Google Drive; SSRF guards + post-redirect host re-validation (`PublicOnlyAsyncTransport`, `assert_public_redirect_target`); scraper read caps |
| api.py | ✅ | /sheet /trackers /stream /metadata /image-proxy /cache-clear (admin-gated); media_kind; 1600px bucket; opt-in per-IP rate limiter (XFF by declared hop count) |
| web/ | ⚠️ Unmaintained | Kept for reference; does not track new backend features |
| tests/ | ✅ | Marker-gated pyramid (see Architecture); bare `pytest` = offline gate; CI in .github/workflows |
| LeakSheet-iOS/ | ✅ | SwiftUI iOS/macOS/tvOS 27+ apps sharing Shared/: Swift 6, Liquid Glass, video playback, tab-mode UI |

The tracker registry is the **live ArtistGrid CSV** (`GET /trackers` / `ARTISTGRID_URL` in
config.py). `Trackers/artists.ndjson` is **deprecated** — don't build new features on it.

### Known Parser Edge Cases (2026-07-20 review)

| Issue | Severity | Description |
|-------|----------|-------------|
| Template/placeholder eras | Low | Sheets with dummy eras ("TBA", "Album Name 4") whose stats text claims songs — parser is faithful; health checks flag them |
| Era-less flat tracklists | Medium | A minority grammar (numbered singles lists, no era column) parses poorly — see docs/reviews/2026-07-20 report follow-ups |
| Alt name grouping | Medium | "Afta U [V1]" and "After You [V2]" not grouped (different base names) |
| Multi-line credits | Low | A credit whose closer sits on the next line (`[prod. A,\nB]`) stays an alt title — spanning newlines lets an unclosed `(prod. ` swallow real alt-title lines |

---

## Key Design Decisions

> Per-branch rationale — why a specific parser/fetcher rule exists and what breaks
> without it — lives in [docs/decisions.md](docs/decisions.md), keyed `file.py::symbol`.
> Source sites carry a one-line pointer. Add an entry there when you fix something whose
> reason isn't obvious from the code.

- **lxml fast path** — `extract_table` uses lxml (~40% faster); the stdlib `_TableExtractor`
  fallback must stay byte-identical in output (verified cell-by-cell in tests)
- **FastAPI + Pydantic** — Lightweight, async, auto-docs, native model serialization
- **httpx** — Async HTTP client for fetching live tracker URLs
- **Column auto-detection** — No hardcoded column indices; parse header row dynamically
- **Version grouping** — Songs with same base name (minus [Vx] tag) grouped as versions of one Song
- **Emoji stripping** — Badge emojis stripped from display name, stored as separate Badge enum field
- **Case-insensitive era matching** — Handles trackers with inconsistent capitalization
- **Images load lazily with cached color seeding** — era colors seed from the persisted extraction cache when a tracker opens; images download per visible card at bucketed sizes. The old "wait for all era images before showing the UI" behavior was removed in the 2026-07-14 perf restructure — do not reintroduce an eager full-tracker image prefetch.

---

## Working Rules (2026-09-23 review)

Learned from ten weeks of review rounds that each had to fix the previous round's fixes.

- **Comments:** at most 2 lines, present tense, only *why* something non-obvious is so. No history ("used to", "was X"), dates, review references or corpus statistics in code: history lives in git, rationale in `docs/decisions.md` / `LeakSheet-iOS/DECISIONS.md`.
- **Commits:** subject line plus a body of at most 8 lines.
- **Concurrency, caching and parsing changes** need a failing test first, and an adversarial review of the diff before merging — not another review round after it.
- **Fix bug classes, not instances:** when one input shape breaks, add a test that covers every place the shape can reach (e.g. `tests/unit/test_regex_linear.py` times every compiled regex in `src/`).
- **Process model:** the API runs 3 gunicorn workers. Anything held in process memory (rate limiter, single-flight, backoff, caches) is per worker. After changing the worker model, grep for "single worker".
- **CI:** never hide a red job behind `continue-on-error`.
- **Parser accuracy:** `tests/tools/yetracker_diff.py` diffs our Ye parse against yetracker.cc, an independent parser. Run it after parser changes.
- **iOS verification:** the Xcode MCP (`mcp__xcode__*`) builds, runs tests and lists issues. To point the simulator at prod without changing a saved dev server: `xcrun simctl launch --terminate-running-process <udid> si.safko.LeakSheet -leaksheet_api_base_url https://sheets.safko.eu/api`.
