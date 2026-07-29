# LeakSheet — Improvement Round: Parser + iOS App

## Context (read first)

Monorepo at `/Users/safko/Dev/LeakSheet`: FastAPI backend (`src/`: `api.py`, `parser.py`,
`fetcher.py`, `streaming.py`, `models.py`, `config.py`), iOS 27 SwiftUI app
(`LeakSheet-iOS/`, Swift 6 strict concurrency, MainActor default isolation), Vue web
frontend (`web/` — **out of scope, do not touch**).

A full review + fix round just merged as PR #9 (branch `fix/review-findings`): parser
era-key registration fix (section labels no longer starve real eras — see the WAR-era
note in `tests/test_snapshot_accuracy.py`), force-refresh cache repopulation
(`write_cache` param in `fetcher.py`), imgur SSRF guard, FlowLayout credits wrap,
queue `artistSlug` threading, video-extension classification in
`MiscLinkClassifier.swift`. Build on that state; don't re-fix those.

Test conventions: pinned-baseline harnesses (`tests/test_snapshot_accuracy.py` over
gzipped snapshots in `tests/fixtures/snapshots/`, `tests/test_fixture_accuracy.py` over
`Trackers/` fixtures). Any parser behavior change MUST update baselines in the same
commit with a dated explanatory comment (see existing notes in BASELINES). Diagnostic
tools live in `tests/tools/` (`census.py`, `inspect_eras.py`, `investigate_mismatch.py`).
Run backend via `.claude/launch.json` ("backend", uvicorn :8000); pytest via
`python3 -m pytest tests/`.

Live tracker URLs for testing (verified working 2026-07-16):
- Ye: `https://yetracker.net` (custom domain; the old Google Sheet ID is dead)
- Travis: `https://docs.google.com/spreadsheets/d/1gJqbQrb3dIWF-PLMsKkNUrftpQb8zxsZFDAIpSvT5Fo/edit?gid=846204501`
- Kendrick: `https://docs.google.com/spreadsheets/d/1i4OQglDHiiqMDthqfUFPutGmpZzK7n63LaoWApqhQXI/edit?gid=1169728352` (note: `Trackers/artists.ndjson` has a stale dead URL)
- Carti: `https://docs.google.com/spreadsheets/d/1Irtfvymu26CShYowLMMfD-rM0o9CJqE6-BBSlYsAaF4/edit?gid=0`
- Discovery: `GET /trackers` scrapes TrackerHub live.

iOS tooling: the Xcode MCP (`xcrun mcpbridge`) only registers tools if Xcode-beta is
open with `LeakSheet.xcodeproj` loaded at session handshake — if its tools are missing,
ask me to reconnect (or drive the bridge over stdio as a fallback; see memory note
`xcode-mcp-bridge-connection`). Simulator: iPhone 17 Pro, iOS 27,
`DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer`. Point the app at the
local backend via UserDefaults key `leaksheet_api_base_url` = `http://localhost:8000`.
iOS unit tests: `xcodebuild test -scheme LeakSheet` (Swift Testing, 143 tests green).

## Phase 1 — Investigate & propose (plan before implementing)

Assess each item below, rank by user impact vs. effort, and present a plan for approval
before large changes. Small, clearly-correct improvements may proceed directly.

### Parser / backend
1. **Parsing accuracy** — run the live parses + snapshot harness; investigate any
   starved/missing/misrouted songs beyond the fixed WAR case. Use
   `LEAKSHEET_ACCURACY_VERBOSE=1` and `tests/tools/` for triage.
2. **Alt-name correctness & linkage** — era `alt_names` come from parenthesized lines in
   header cells (`parser.py` `_parse_era_header_row`). Check: multi-alt splitting
   (comma-separated lists inside one paren), song-level `alt_titles`, and whether a song
   row referencing only an alt name reliably lands in the right era (exact → stripped →
   fallback-dict → fuzzy chain in `parse_sheet`).
3. **Cross-era song linkage** — same song appearing in multiple eras (e.g. "This One
   Here" in WAR/DONDA 2/YEBU/¥$). Consider a stable song identity (normalized
   name + credits hash?) exposed in the API so clients can link versions across eras.
4. **Misc entries → era grouping** — `MiscEntry` already carries `era_name`
   (`models.py`); the iOS Misc mode renders a flat list. Group by era in the UI (and/or
   nest in the API response) instead.
5. **Image quality** — era art URLs are Google-hosted; the backend `/image-proxy`
   resizes to buckets [128, 320, 640, 1280] and rewrites Google `=s` size params. Check
   whether we request large enough source sizes for the Now Playing full-screen art.
6. **Parse remaining tabs** — tab discovery/classification lives in
   `fetcher.py` (`_discover_named_tabs`, keyword sets around lines 103–118, currently:
   Art / Misc / Music-Videos / Unreleased). Investigate parsing Released / Best-Of /
   Stems / other tabs. Open design question (propose, don't just build): how to
   classify tab kinds reliably across trackers, and how the client should present
   them — probably as additional switchable modes like the existing Misc mode.

### iOS app
7. **Tracker loading** — cold-load UX for huge payloads (Ye JSON is ~7.8MB,
   gzip-compressed on the wire; decode + first render cost). Consider streaming/partial
   render or progress feedback.
8. **UI/UX polish** — with `/frontend-design` as the lens; screenshots as evidence.
   Known leftovers from the last review: search-lag feel on broad queries (spinner
   `isFiltering` exists — verify it's actually visible), URL field select-all-on-focus.
9. **Playback quality** — `/stream` proxies pillows.su/imgur.gg/froste.lol/krakenfiles
   with Range synthesis; froste needs MIME sniffing for FLAC. Verify no transcoding/
   quality loss and correct format handling end-to-end (`AudioEngine` + `/metadata`).
10. **In-app integrations** — links to pixeldrain, YouTube, SoundCloud, Google Drive
    currently open externally (`MiscLinkClassifier` + `handleLinkSelection`). Evaluate
    per-host: in-app playback (backend proxy extension?) vs. SFSafariViewController vs.
    keep external. Mind each host's ToS and the SSRF allowlist pattern in `api.py`.
11. **Music-video playback** — partially fixed: video FILE EXTENSIONS now classify as
    `.video` and open externally. Still broken: extension-less stream-host video files,
    e.g. `https://pillows.su/f/d78250792a0732d224e94ed8d2545a0c` (an .mp4 behind an
    opaque id) — classification can't see the container. Needs (a) a metadata probe
    (`/metadata` already returns container info for pillows) or AVPlayer video-track
    detection, and (b) an actual in-app video surface: `NowPlayingView` has NO
    VideoPlayer/AVPlayerLayer — add one bound to `AudioEngine`'s AVPlayer, shown when
    the current item has a video track.
12. **Settings/tabs/features** — propose options and app-level tabs that fit an
    info + playback app; get approval before building.
13. **Tests & caching** — extend `LeakSheetTests` where fixes land; review
    `CacheService`/`ImageCache` (`NSCache` 300 items/128MB, URLCache 20/150MB) and the
    ETag/304 flow in `APIClient`.

### Language migration assessment (assessment ONLY — no rewrite without approval)
Profile the actual API bottlenecks first (parse: Ye 11.7MB HTML ≈ 0.9s via lxml; warm
cache hits ≈ 2ms; cold time is dominated by fetching Google's HTML — network-bound).
Then evaluate whether Rust or Bun would meaningfully help vs. Python+lxml+uvicorn,
counting maintenance cost and the existing 450-test suite. Deliver a short
recommendation with numbers; do not start a migration.

### Documentation check
Verify backend library usage against current docs (FastAPI/Starlette middleware, httpx
streaming + Range/RFC 7233, Pydantic v2 — `fetcher.py` still calls deprecated
`parse_obj`; PIL). Use Context7 for docs. iOS was already written against iOS 27
docs via Xcode skills — spot-check only what you touch (load
`anthropic-skills:swiftui-specialist` and `swiftui-whats-new-27` when editing SwiftUI).

## Phase 2 — Implement approved improvements
Work on a feature branch. TDD where practical: failing test → fix → baseline updates
in the same commit. Subagents: use sonnet.

## Phase 3 — Verify + code review
- Backend: full pytest; live-parse all four trackers; compare era/song/version counts
  against baselines; cold/warm latency check.
- iOS: build + full unit tests + simulator walkthrough of every changed screen with
  screenshot evidence (music-video playback verified against the pillows.su URL above).
- Then run a code review pass (sonnet subagents) over both codebases' changed areas.
- Web is out of scope entirely.


Original prompt:
Our next step is to see if any improvements can be made to the parser or ios app.



For parser consider improving:

parsing accuracy
Alt name correctness
Linking alt + normal names, so songs with only one are correctly assigned
Cross era song linkage (same song, but diffrent era)
Misc era displayal (entries are now just shown, not tied to era)
Improving image quality
Parsing other tabs, to offer user entries from those tabs (but not sure how to present, and not sure how to tell each tab (unreleased, released, best of, worst of, other, misc, music videos...) for each tracker

For ios app consider imrpoving:
tracker loading
UI improvements
UX imrpovements
Sound quality for playback from media sites
Direct integrations in app, instead of sending user to other sites (pixeldrain, youtube, soundcloud, google drive...)
Adding options, adding tabs...
Improving tests
adding functionality that is good for this style of app (info + playback)
Improving caching
Music video playback (currently some entries wont play - ex. ye tracker, pillows.su .mp4 file https://pillows.su/f/d78250792a0732d224e94ed8d2545a0c)


Check these and consider improving the quality of both of the codebases.

A program language change is possible to improve performance of api. Check if other language would help, or be easier to maintain (rust, bun?)
Check with documentation if the methods used in our app are correct. Mostly for the api, ios was documented for ios27, using xcode skills, but you may verify.
After these changes are implemented, preform a code review of both apps. Web is not needed.
