# AGENTS.md

LeakSheet parses Google Sheets music-leak trackers into JSON (FastAPI, `src/`) for native
SwiftUI apps (`LeakSheet-iOS/`: iOS, macOS and tvOS from one project).

## Commands

- `uv run pytest` — the offline gate: markers exclude `live`/`accuracy`/`slow`, and
  `tests/conftest.py` refuses network access.
- `uv run pytest -m live` (real trackers) · `uv run pytest -m accuracy` (local corpus + labels)
- `uv run ruff check .`
- `uv run uvicorn src.api:app --reload` — local API on :8000.
- `uv run python -m tests.parse.test_wire_contract` — regenerate the Swift contract fixture
  after an intended change to the `/sheet` wire format.
- `uv run python tests/tools/yetracker_diff.py` — diff the Ye parse against yetracker.cc, an
  independent parser. Run it after parser changes.
- `k6 run tests/load/api.js` — load test of the hot paths; CI runs it on the Docker image
  with a seeded cache. `k6 run -e PROFILE=smoke tests/load/journey.js` — an app user's journey
  through the public domain (profiles in the file header; the `load-prod` workflow runs it too).
- iOS: the Xcode MCP (`mcp__xcode__*`: BuildProject, RunAllTests) or
  `xcodebuild test -project LeakSheet-iOS/LeakSheet.xcodeproj -scheme LeakSheet -destination 'platform=iOS Simulator,name=iPhone 17 Pro'`.
  Also build the `My Mac` destination and the `LeakSheetTV` scheme: they compile their own views.
- Deploy: `ops/deploy.sh` on the server. Never `docker compose up` in the checkout.

## Layout

- `src/api.py` — HTTP layer: `/sheet` (ETag, stale-while-revalidate, NDJSON progress),
  `/trackers`, `/stream`, `/image-proxy`, `/metadata`, `/cache/clear`, `/health`
- `src/fetcher.py` — fetching, tab discovery, disk cache · `src/parser.py` — HTML → `Artist`
- `src/models.py` — Pydantic models; their `dict()` overrides define the wire format
- `src/streaming.py` — stream URL resolution and the SSRF-guarded httpx transport
- `src/config.py` — column aliases, host allowlists, `VERSION` (read from pyproject.toml)
- `tests/` — `unit/`, `parse/`, `fetch/`, `api/` (offline gate), `live/`, `quality/`
  (accuracy), `fixtures/synthetic/` (invented content only), `tools/`
- `LeakSheet-iOS/Shared/` — models, services (APIClient, CacheService, AudioEngine,
  PlaybackQueueLogic), view models; `LeakSheet/` iOS + macOS views; `LeakSheetTV/`
- `web/` — the nginx front (config only) · `ops/` — deploy script, CasaOS app definitions

## Invariants

- Never commit real tracker content (DMCA). Tests use `tests/fixtures/synthetic/` only.
- The API runs 3 gunicorn workers: anything in process memory (rate limiter, single-flight,
  backoff, caches) is per worker. After changing the worker model, grep for "single worker".
- Cached parsed bytes are the wire bytes: a serialization change changes every ETag, and
  removing a field needs a cache version bump.
- The Swift side decodes some types through explicit CodingKeys (e.g. `MiscEntry`); the
  shared contract fixture fails when the two sides drift.
- Swift: default MainActor isolation; value types used off the main actor are `nonisolated`.

## Working rules

- **Comments:** at most 2 lines, present tense, only *why* something non-obvious is so. No
  history ("used to", "was X"), dates, review references or corpus statistics in code:
  history lives in git, rationale in `docs/decisions.md` / `LeakSheet-iOS/DECISIONS.md`.
- **Commits:** subject line plus a body of at most 8 lines.
- **Concurrency, caching and parsing changes** need a failing test first, and an
  adversarial review of the diff before merging, not another review round after it.
- **Fix bug classes, not instances:** when one input shape breaks, add a test that covers
  every place the shape can reach (e.g. `tests/unit/test_regex_linear.py` times every
  compiled regex in `src/`).
- **CI:** never hide a red job behind `continue-on-error`.

## Docs

- `docs/decisions.md`, `LeakSheet-iOS/DECISIONS.md` — why non-obvious code is the way it
  is, keyed `file::symbol`; source sites carry a one-line pointer.
- `README.md`, `LeakSheet-iOS/README.md`. Local, untracked notes may live in `AGENTS.local.md`.
- `docs/ROADMAP.md` — deferred work (e.g. a .NET rewrite) and what would trigger it.
