# LeakSheet iOS — Specification

> Auto-generated reference from the LeakSheet web app analysis.
> Target: SwiftUI, iOS 26+, Swift 6, Liquid Glass design language.

---

## 0. Architecture

- **Language:** Swift 6 (strict concurrency)
- **UI:** SwiftUI, iOS 26+
- **Build settings:** `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`, `SWIFT_APPROACHABLE_CONCURRENCY = YES`
- **Navigation:** `NavigationStack(path:)` with type-safe `.navigationDestination(for: Artist.self)`
- **State:** `@Observable` macro (Observation framework), `@Environment` injection
- **Services:** `actor`-isolated (`APIClient`, `CacheService`, `ImageCache`, `EraColorExtractor`)
- **Audio:** `@MainActor @Observable AudioEngine` singleton with AVPlayer
- **Models:** `nonisolated` Codable structs (opt out of default MainActor isolation)
- **Dependencies:** Zero third-party

### File Structure (36 files)
```
LeakSheet/
├── LeakSheetApp.swift
├── ContentView.swift
├── Models/
│   ├── Models.swift              # Artist, Era, Section, Song, SongVersion, Badge, etc.
│   └── StreamResolver.swift      # Streamable URL pattern matching
├── Services/
│   ├── APIClient.swift           # HTTP client actor (sheet, image-proxy, metadata, stream)
│   ├── AudioEngine.swift         # AVPlayer + MPNowPlayingInfoCenter + queue management
│   ├── CacheService.swift        # Disk cache actor with ETag validation
│   └── ImageCache.swift          # In-memory NSCache + URLSession image loader
├── ViewModels/
│   ├── ArtistViewModel.swift     # Search, filter, recents, era state (470+ lines)
│   ├── PlayerViewModel.swift     # Thin @Observable wrapper over AudioEngine
│   ├── FavouritesManager.swift   # UserDefaults persistence singleton
│   └── RecentTrackersManager.swift
├── Views/
│   ├── Landing/
│   │   ├── LandingView.swift
│   │   ├── TrackerInputView.swift
│   │   ├── BrowseArtistsView.swift     # Artists.ndjson discovery list
│   │   └── RecentTrackerCardView.swift
│   ├── Artist/
│   │   ├── ArtistView.swift
│   │   ├── ArtistStatsBarView.swift
│   │   ├── EraCardView.swift
│   │   ├── EraNavView.swift
│   │   ├── SongListView.swift
│   │   ├── SongRowView.swift
│   │   ├── VersionRowView.swift
│   │   ├── BadgeRowView.swift
│   │   ├── CreditTagsView.swift
│   │   └── SongContextMenu.swift       # Shared context menu + 3-dot menu
│   ├── Player/
│   │   ├── MiniPlayerBar.swift
│   │   └── NowPlayingView.swift        # Full-screen now-playing
│   └── Shared/
│       ├── CachedImage.swift           # ImageCache-backed AsyncImage replacement
│       ├── SongDescriptionSheet.swift  # Includes FlowLayout
│       ├── QueueSheet.swift
│       ├── FavouritesView.swift
│       └── SettingsView.swift          # Cache clear, about info
└── Utilities/
    ├── DesignTokens.swift        # Color/spacing constants
    ├── EraColorExtractor.swift   # Dominant color from cover art
    └── Haptics.swift             # UIKit haptic feedback helpers
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

  ArtistView (system back gesture)
  ├── NoticeBanner         — alert/info dismissible banners
  ├── ArtistStatsBar       — total / available / snippets / full HQ
  ├── .searchable()        — debounced search with filter toggles (Liquid Glass)
  ├── FilterChips          — Best Of / Recents / No Snippets (Liquid Glass tinted)
  ├── EraNav               — side rail with era abbreviation buttons (Liquid Glass)
  └── ScrollView
       └── LazyVStack of EraCards
            ├── Cover art + gradient (dominant color)
            ├── Title + alt names + timeline
            ├── Collapsible description
            └── SongList
                 ├── Section headers (sticky)
                 └── SongRows
                      ├── Badge + title + version tag + badges + length
                      ├── Swipe right = play, left = queue
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
  ├── BrowseArtistsView    — searchable artists.ndjson list
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
Providers: pillows (codec/bitrate/duration), froste (quality analysis), imgur (file info)
Response: { provider, codec?, bitrate?, sample_rate?, duration?, ... }
Cached: max-age=3600
```

### GET /api/stream?url=...&download=false
```
Proxies audio stream from supported file hosts.
Hosts: pillows.su, pillowcase.su, imgur.gg, temp.imgur.gg, music.froste.lol, krakenfiles.com
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
versions: [SongVersion]
badge: String? (computed)       // from any version
available_length: String?       // from primary version
quality: String?
track_length: String?
leak_date: String?
file_date: String?
```

### SongVersion
```
name: String
version_tag: String?            // "V1", "V2", "Alt.", "Radio Mix", etc.
badge: String?                  // "best", "special", "worst", "grail", "wanted", "ai"
featuring: String?
producers: String?
collaboration: String?
refs: String?
alt_titles: [String]
notes: String?
og_filename: String?
samples: [String]
track_length: String?
file_date: String?
leak_date: String?
available_length: String?       // "Full", "Partial", "Snippet", "Confirmed", etc.
quality: String?                // "CD Quality", "High Quality", "OG File", etc.
links: [String]
quality_color: String?          // hex background color
available_length_color: String?
date_of_recording: String?      // Carti-specific
type: String?                   // Carti-specific
```

### Badge (String enum)
```
best     — ⭐ / 💎
special  — ✨
worst    — 🗑️
grail    — 🏆
wanted   — 🏅 / 🥇 / 🥉
ai       — 🤖
```

### EraStats
```
og_files: Int
full: Int
tagged: Int
partial: Int
snippets: Int
stem_bounces: Int
unavailable: Int
total: Int (computed)           // sum of all
```

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

### ParseMetadata
```
total_rows, song_rows, skipped_rows, footer_rows, fuzzy_matched_rows: Int
unmatched_rows: [String]
```

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
links_work: Int?                // 0/1 flag
updated: Int?                   // 0/1 flag
best: Bool?                     // recommended tracker
```

---

## 4. Audio Playback

### Stream Resolution (client-side)
All audio streams go through `/api/stream?url=<encoded_original_link>`.
Supported host patterns:
- `pillows.su/f/{id}`, `pillowcase.su/f/{id}`
- `imgur.gg/f/{id}`, `temp.imgur.gg/f/{id}`
- `music.froste.lol/song/{hash}`
- `krakenfiles.com/view/{id}/file.html`

Regex for streamable link detection:
```
^https?://(?:(?:www\.)?(pillows\.su|pillowcase\.su|(?:temp\.)?imgur\.gg)/f/|music\.froste\.lol/song/[a-f0-9]+|(?:www\.)?krakenfiles\.com/view/[A-Za-z0-9_-]+/file\.html)
```

A version with `og_filename` ending in `.zip` is NOT streamable.

### Original Quality URLs
- pillows: `https://api.pillows.su/api/download/{id}`
- froste: `https://music.froste.lol/song/{hash}/download`
- imgur/kraken: same URL (CDN serves original)

### Queue
- Max 200 items
- Each item: { id, version, artistName, eraName, artUrl }
- Auto-advance: queue first → era songs → stop
- Reorderable via drag
- Swipe-to-delete

### Background Audio
- AVAudioSession category: `.playback`
- MPNowPlayingInfoCenter: title (with badge emoji + version tag), artist, album (era name), artwork (proxied cover art)
- MPRemoteCommandCenter: play, pause, nextTrack, previousTrack (restart if >3s), seekForward (+10s), seekBackward (-10s), changePlaybackPosition

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
1. ▶ Play / ⏸ Pause (if currently playing)
2. Add to Queue
3. ♥ Favourite / Unfavourite
4. ℹ Show Description
5. 🔗 Copy Link (if links exist)
6. 🌐 Open in Safari (if links exist)
7. ⬇ Download (if streamable)

Used as both `.contextMenu` and `ThreeDotMenu` (ellipsis button) on SongRowView and VersionRowView.

### Haptic Feedback
- Swipe trigger: `.medium` impact
- Long-press: `.light` impact
- Favourite toggle: `.light` impact
- Error: `.error` notification

---

## 6. Search & Filtering

### Search Scoring (3 tiers)
1. **Tier 1 (exact start, score 100):** base_name starts with query
2. **Tier 2 (word boundary, score 60):** query matches start of any word in name/alt_titles/credits
3. **Tier 3 (substring, score 30):** query found anywhere in name/alt_titles/featured/producers/collaboration/refs/notes

Pre-build search index per song (lowercased concatenation of all searchable fields).
Debounce: 200ms via Task.sleep.

### Filter Toggles
- **Best Of:** Show only songs with badge ∈ {best, special}
- **Recents:** Show only songs with leak_date in last 30 days (parse "Month DD, YYYY" or "YYYY-MM-DD")
- **No Snippets:** Hide songs where ALL versions have available_length containing "snippet" (case-insensitive)

---

## 7. Caching

### API Response Cache
- Store: URL → { data: Artist JSON, etag: String, timestamp: Date }
- On request: send `If-None-Match: <etag>` → 304 means use cached data
- Storage: FileManager Caches directory (JSON files) or SwiftData
- Single tracker cached at a time (matching web behavior)

### Favourites
- UserDefaults with key `leaksheet_favourites`
- Array of FavouriteEntry: { key, artistSlug, artistName, sourceUrl, eraName, eraArt, song, addedAt }
- Composite key: `{artistSlug}::{eraName}::{baseName}`

### Recent Trackers
- UserDefaults with key `leaksheet_recent_trackers`
- Cap: 20 entries
- Each: { url, artistName, slug, totalSongs, totalVersions, timestamp }

### Volume
- UserDefaults with key `leaksheet_volume` (Float 0-1)

### Era Colors
- In-memory dictionary + UserDefaults (max 200 entries)
- Key: art_url → Value: dominant color hex

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
Display (headings): SF Pro Rounded Bold/Heavy (replaces Outfit)
Body:               SF Pro (system default, replaces Inter)
Base size:          14pt (body), scalable with Dynamic Type
```

### Spacing & Radius
```
radius-sm:  6pt
radius-md:  10pt
radius-lg:  16pt
player-height: 72pt (mini), expandable
```

### Liquid Glass (iOS 26)
```swift
// Mini player bar — floating glass pill
.glassEffect(in: .rect(cornerRadius: 16))

// Era navigation rail — glass pill
.glassEffect(in: .rect(cornerRadius: 8))

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
- EraNavView (glass pill)
- TrackerInputView (tinted on focus)
- ArtistView FilterChip (tinted on active)
- ArtistView search field
- LandingView Browse Artists button
- ArtistView navigation toolbar (automatic)

---

## 9. Era Color Extraction

1. Load cover art via AsyncImage / URLSession
2. Get UIImage, crop to center 50% area
3. Sample pixels (stride every 4th pixel)
4. Build hue histogram, find dominant bucket
5. Compute HSL variants:
   - Background: HSL(hue, 30%, 8%) — very dark tinted
   - Border: HSL(hue, 40%, 15%)
   - Text accent: HSL(hue, 60%, 70%)
   - Gradient: linear from bg color to transparent
6. Cache: artUrl → color in UserDefaults (max 200)

---

## 10. Animations

### Equalizer Bars (playing indicator)
- 2 bars oscillating height 3pt ↔ 12pt
- Different animation durations (0.4s, 0.5s) for variety
- Respect `UIAccessibility.isReduceMotionEnabled`

### Stagger Entry
- Era cards: delay = index * 0.05s, ease-out
- Song rows: similar stagger within era

### Accordion Expand
- `withAnimation(.easeInOut(duration: 0.25))`
- Height transition for version list

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
1. If quality is empty/"Not Available": show availability badge only
2. If quality == availability (same text): show quality only
3. Otherwise: show quality badge + availability badge side by side

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
