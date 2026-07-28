# Security review — backend + iOS, 2026-07-27

**Scope:** `src/` and `LeakSheet-iOS/`. The web app is out of scope permanently.
**Why now:** the 2026-07-21 pass hardened the stream and image paths; the 2026-07-24
maintainability round explicitly descoped security again while rewriting the sync entry
points and trimming the wire format (PRs #15/#16). Nothing had been security-reviewed since.
The server is public (`sheets.safko.eu`), so findings are real.

**Baseline:** offline gate 495 → 540 · accuracy 72, both green throughout.

---

## HIGH — fixed

### 1. `POST /sheet` was an unguarded SSRF sink

`/sheet` takes a URL from the caller and fetches it server-side. `_get_sheets_client()` had
`follow_redirects=True`, no host allowlist, and none of the `PublicOnlyAsyncTransport`
protection the stream and image clients received in July.

Reachable as a result:

| Target | Effect |
|---|---|
| `http://169.254.169.254/latest/meta-data/` | cloud instance metadata |
| `http://127.0.0.1:<port>/…` | anything bound to loopback |
| `http://10.0.0.0/8`, `172.16/12`, `192.168/16` | the platform's private network |

Worse than blind SSRF: `parse_sheet` runs on whatever comes back, so **any internal page
containing a `<table>` was parsed and returned to the caller**. And the error mapping is
granular — `InvalidURLError`→400, `NoTablesError`→404, `NetworkError`→502,
`AccessDeniedError`→403 — which makes the endpoint an internal host and port scanner even
when the body is empty.

**Fixed** with a host allowlist enforced on the normalized URL before any network call, in
both `async_fetch_sheet_html` and `async_fetch_and_parse`:

- seed: `docs.google.com`, `drive.google.com`, plus the two known custom-domain trackers
  (`yetracker.net` — the README's CLI example — and `deftonestracker.net`, the only
  non-Google host among the 414 trackers in the 2026-07-20 sweep);
- runtime: hosts of trackers listed in the TrackerHub feed, so a newly listed tracker works
  without a deploy. An allowlist miss buys **at most one feed refresh per 15 minutes**
  (`TRACKER_HOST_REFRESH_INTERVAL`) — otherwise a flood of bogus hosts turns the guard into
  a request amplifier;
- escape hatch: `LEAKSHEET_EXTRA_SHEET_HOSTS` (comma-separated).

Matching is exact, so an attacker-controlled `evil.docs.google.com` is not admitted.

Defence in depth: the sheets client now uses `PublicOnlyAsyncTransport`, which re-checks at
connect on **every redirect hop**, so an allowed host cannot 30x the fetch inward.

**Accepted trade-off (operator's call):** a tracker on a brand-new custom domain that is not
yet in the TrackerHub feed returns 400 until the feed catches up or the env var is set. The
error names the cause explicitly rather than reading as a parse failure.

Tests: `tests/unit/test_sheet_host_allowlist.py`, `tests/api/test_sheet_endpoint.py::TestSSRFGuard`
(the latter runs the real pipeline — a regression that removes the guard fails there rather
than silently reaching out).

---

## MEDIUM — fixed

### 2. Host harvesting was far looser than intended

The first cut of the allowlist refresh scraped every `href` on the TrackerHub page, which
admitted `discord.gg`, `www.reddit.com`, `ssl.gstatic.com` and `madisonbeer.fandom.com` from
the page furniture — quietly widening what the backend would fetch on request.

Harvesting now reads the **parsed feed rows** (`parse_trackerhub`), which already discards
banner rows. Live check: 2 hosts (`docs.google.com`, `deftonestracker.net`), down from 7.

This required lifting `parse_trackerhub` and `TrackerEntry` out of the API layer into
`parser`/`models` so the fetcher can reach them — which also retired
`_unwrap_google_redirect` as a duplicate of `parser._clean_link`.

### 3. Rate limiter bucketed every caller together

`_RateLimitMiddleware` keyed on `scope["client"]`. In production the app sits behind a
platform router, so that is the *router's* address for every request: enabling
`LEAKSHEET_RATE_LIMIT_PER_MIN` would have throttled the entire user base as one bucket —
a self-inflicted DoS rather than a protection. (The limiter is opt-in and currently off,
so this was latent.)

**Fixed** with `_client_ip()`: `X-Forwarded-For` is caller-controlled, so it is consulted
only when the operator declares how many proxy hops to trust via
`LEAKSHEET_TRUSTED_PROXY_HOPS`, and the entry is counted **from the right** — the portion a
client cannot forge. A chain shorter than the declared hop count means the request did not
arrive through the expected path, so nothing in it is trusted and the peer address is used.
Tests: `tests/api/test_rate_limit.py::TestClientIPResolution`.

---

## Audited, no action needed

- **`GET /metadata`** — cannot be pointed anywhere. `resolve_metadata_url` matches
  anchored per-provider patterns and rebuilds the URL from a hardcoded host template with
  only an ID interpolated; every ID capture is `[A-Za-z0-9_-]+` or `[a-f0-9]+`, so no `/`,
  `:`, `@` or `.` can smuggle in a host. The shared client also carries
  `PublicOnlyAsyncTransport`.
- **`GET /image-proxy`** — domain allowlist plus parent-domain check, decode-pixel and
  input-byte caps, atomic cache writes, `PublicOnlyAsyncTransport` on its client.
- **`POST /cache/clear`** — admin-token gated, fail-closed when the token is unset, compares
  `.encode()`d bytes (so a non-ASCII token can't `TypeError`). Unchanged since 2026-07-21
  and still correct.
- **`GET /stream`** — host allowlist derived from `ALLOWED_STREAM_HOSTS` (single source
  shared with the resolver), post-send redirect re-validation, capped scraper reads.
- **`_StreamSafeGZipMiddleware`** — compression is skipped for `/stream` and `/image-proxy`.
  No BREACH exposure on the remaining JSON routes: responses carry no secrets and no
  per-user state.
- **`asyncio.run` wrappers** (PR #15) — `_run_sync` creates a private loop and closes the
  loop-bound shared client in a `finally`. No cross-loop reuse.
- **Prewarm / background revalidate** — both route through `async_fetch_and_parse` and so
  inherit the new host guard. The URLs they replay come from cache entries that already
  passed it.
- **`/sheet` cache fast paths** — the ETag-304 and stale-while-revalidate paths answer
  before the host guard, but nothing reaches the cache without having passed it, so they
  cannot be used to reach a new host.
- **Hub-workbook aggregation** (new this round) — only ever fetches sibling GIDs of the
  already-validated workbook URL.
- **iOS** — no `NSAppTransportSecurity` exception in `Info.plist`, so ATS defaults apply and
  plain HTTP is blocked. The custom `baseURL` in Settings is user-entered and falls back to
  the production HTTPS default when unset or unparseable; that is the intended dev affordance,
  not an injection point. No credentials are stored; `UIBackgroundModes` is `audio` only.

---

## Known limitations (unchanged, documented)

- **DNS-rebinding residue.** `PublicOnlyAsyncTransport` resolves and checks at connect, which
  narrows but does not close the TOCTOU window against a hostile allowlisted host. Fully
  closing it needs exact-IP pinning per connection, which requires live verification against
  each upstream. The allowlist now makes the precondition much harder to reach.
- **Host lists duplicated in three places** — backend regexes, `_STREAM_ALLOWED_DOMAINS`,
  iOS `StreamResolver`. In sync today, drift-prone by construction. Flagged since 2026-07-20.
- **Rate limiter is in-process**, correct only because the Procfile runs a single worker. A
  second worker would double the effective limit.

---

## Verdict

**Approve.** The one HIGH (a fully unguarded SSRF sink on the most-used endpoint) and both
MEDIUMs are fixed and test-gated. Everything else reviewed this round holds up.
