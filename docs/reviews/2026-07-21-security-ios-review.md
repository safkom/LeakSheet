# Deep Review: security (backend) + iOS correctness/UX — 2026-07-21

**Scope:** whole codebase except the web app — `src/` (API/parser/streaming) and
`LeakSheet-iOS/`. **Method:** read-only multi-agent review (adversarially verified findings)
across 7 streams, gaps completed by direct source review; every HIGH verified against code.
This is the **security pass the 2026-07-20 review explicitly descoped to a dedicated Opus
session**, plus the first deep iOS code/UX review since 2026-07-06.

## Verified baseline (no action needed)

- Offline gate **472→478 passed**; accuracy suite **72 passed / 0 failed** — the "stale
  accuracy baseline" follow-up was already resolved (baselines re-pinned 2026-07-17; Ye
  3977/9141, Kendrick 738/977, Carti 1193/1616, Keem 198/287). Parser is sound.
- API performance is well-engineered: the cold-path parse and all serialize/hash/image/
  trackerhub work are offloaded via `asyncio.to_thread` — nothing CPU-bound blocks the
  single-worker event loop.
- `AudioEngine` KVO/observer lifecycle, actor isolation, and race guards are correct;
  `CacheService`/`ImageCache` are sound.

## Fixed and test-gated this session

### Backend security (`src/`) — server is public (`sheets.safko.eu`)
1. **SSRF-after-redirect (HIGH).** `stream_audio` followed redirects but never re-validated the
   final host (only gdrive did) → a guard-passing public origin could 302 to `169.254.169.254`.
   Added `assert_public_redirect_target` (post-send re-check) on the stream path and a
   `PublicOnlyAsyncTransport` that rejects non-public hosts at connect on every hop (also on the
   image-proxy client), narrowing the DNS-rebind TOCTOU.
2. **Unauthenticated `/cache/clear` (HIGH).** Now requires `X-Admin-Token == LEAKSHEET_ADMIN_TOKEN`;
   disabled (503) when unset (fail closed).
3. **MIME-sniff connection leak (MED):** the first-chunk sniff read now closes the upstream
   response on a read error.
4. **Scraper read caps (LOW):** krakenfiles/gdrive HTML reads capped at 512 KB
   (decompression-bomb guard).
5. **Ogg sniff (NIT):** requires a genuine `OggS` prefix.
6. **Opt-in per-IP rate limiter** (`LEAKSHEET_RATE_LIMIT_PER_MIN`, pure-ASGI).
   Tests: `test_cache_clear` auth contract + `test_ssrf_guard` redirect-rejection/transport.

### iOS correctness (`LeakSheet-iOS/`)
7. **Placeholder-song row collision (HIGH).** Same-`baseName` songs ("???"/"Unknown", which the
   parser deliberately keeps distinct per era) shared one `EraRow.id`, so SwiftUI's `ForEach`
   dropped duplicates and they shared expand/favourite state. Row identity + expand key are now
   positional via a per-era `ordinal`. Regression test added.
8. **Best Of on Misc entries (MED):** matched any badge incl. worst-of/AI; now `Badge.isBestOf`.
9. **`credited_artists` (MED):** now decoded and surfaced (distinct from `featuring`).
10. **Stats divergence (MED):** `RecentTrackersManager` now delegates to the single stats source
    so the recents card and artist view agree on "confirmed".
11. **gdrive host parity (MED):** `StreamResolver` now recognises `open?id=`/`uc?id=`.

### iOS UX / accessibility
12. Eras branch empty state; Reduce-Motion gate on the now-playing symbol effect; Explore
    Trackers retry button; 44 pt tap targets; info-text contrast (`.tertiary`→`.secondary`);
    "More options" VoiceOver label; swipe-to-play from search/recents now continues down the
    list (was single-track).

### iOS perf / tests
13. `FavouritesManager.save()` moved off the main actor + debounced; `AudioEngine` volume-0
    persistence and `H:MM:SS` duration; the shared-httpx-client reset is now suite-wide in the
    top-level conftest (closes a latent offline-test flake).

## Deferred (tracked follow-ups)

- **Decomposition:** `ArtistViewModel`/`ArtistView`/`SongDescriptionSheet` extract-subview seams
  (large refactor, no behavior change).
- **iOS XCUITest smoke** target (infra).

## 2026-07-22 continuation — documentation-grounded audit + remaining follow-ups

A documentation review (httpx / Starlette via Context7; Swift concurrency / SE-0461 via
Apple/Swift docs) confirmed the httpx SSRF mechanics and Starlette middleware pattern are
correct, and found **3 issues — now fixed & test-gated**:
- **[regression]** `FavouritesManager.persist` was `nonisolated async`, but the target sets
  `SWIFT_APPROACHABLE_CONCURRENCY=YES` (SE-0461), so it ran on the caller's actor (MainActor) —
  the "off-main" save didn't leave the main thread. Marked `@concurrent`.
- Rate-limit 429 carried no CORS header (limiter was outermost); CORS is now registered last so
  it wraps the limiter.
- `hmac.compare_digest` could `TypeError` on a non-ASCII admin token; compares bytes now.

And the deferred follow-ups were implemented & test-gated:
- **CI count gate** — `tests/fixtures/synthetic/era_routing.html` + placement assertions pin the
  era-routing path (sibling eras, digit-leading names, `???` placeholders) in the offline gate.
- **Search index** — per-song lowercased haystack precomputed off-main; ranking pinned identical
  to inline scoring.
- **FlowLayout** — extracted and applied to `BadgeRowView`/`MiscEntryRowView` (pills wrap at AX
  Dynamic Type).
- **Pull-to-refresh + data-age** — `.refreshable` rebuilds the VM from a forced refetch; an
  "Updated N ago" chip shows freshness.

Only decomposition and an iOS XCUITest smoke remain deferred.

## Verdict

**Approve.** The two HIGH security issues and the HIGH iOS row-collision are fixed and
test-gated, as are the doc-audit findings and the implemented follow-ups. Latest:
offline gate 486 · accuracy 72 · iOS 198, all green.
