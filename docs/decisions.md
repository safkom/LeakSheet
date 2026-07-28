# Parser & fetcher decisions

Why the non-obvious branches in `src/` look the way they do. Each entry is the
*history* behind a rule — the evidence that produced it and what breaks without it.
The source keeps a one-line pointer plus whatever warning a future reader needs; the
archaeology lives here so the hot files stay readable.

Entries are keyed `file.py::symbol`. Add to this file when you fix something whose
rationale isn't obvious from the code, and leave a `see docs/decisions.md` pointer
at the site.

---

## parser.py::parse_sheet — era header checked before section separator

The era-header test must run **before** both the section-separator test and the
footer test.

- *Before the separator*: a sparse two-cell header (stats + `Collaboration with X`)
  otherwise gets swallowed as a separator and the era is never created. A genuine
  separator row never carries era stats in column 0, so the ordering is safe.
- *Before the footer*: Carti's era stats contain "Total Full", which is also a
  footer keyword.

Matching an era header also resets footer state: if data resumes after a
footer-looking row, it's a new era, not leftover footer.

Found in the 2026-07-20 review.

## parser.py::parse_sheet — positional-prior era matching

Two rules, both from the 2026-07-20 review, both guarding the same failure: a
similarly-named **sibling era** stealing every row from the era a song actually
sits under, starving it.

1. **Exact positional prior.** If a row's era value names the era we are currently
   under — any of that era's own key forms — it belongs there, full stop. Sibling
   eras that share a stripped key (`Fre3$tyle [V2]`/`[V3]`,
   `38 Baby 2 [V1] / …`/`[V3] / Post`) otherwise route every bare row to whichever
   sibling registered the shared key first. Cases: Glocky, NBA Youngboy.

2. **Fuzzy positional prior**, applied before the global fuzzy search. A row-era
   value that fuzzy-matches the current header is an abbreviation of it — e.g.
   `Get Rich Or Die Tryin' OST` rows directly beneath a
   `Get Rich Or Die Tryin' Soundtrack` header. The global search would let a
   similarly-worded sibling outscore it (`Get Rich Or Die Tryin'` scores 4/4 = 1.0
   against the header's 4/5 = 0.8) and silently steal the lot. Case: 50 Cent.

**When touching era matching, verify PLACEMENT, not just counts** — the accuracy
suite counts totals, so a wholesale re-attribution between two eras passes it.

## parser.py::parse_sheet — auto-created eras keep their row's song

When a row names an era that doesn't exist yet, the branch that creates it used to
drop the parsed version on the floor: silent data loss, not even counted as
skipped. The no-current-era auto-create path had always kept it; the two agree now
(2026-07-20 review).

## parser.py — dedicated credit and filename columns

From the 2026-07-20 TrackerHub sweep, all user-confirmed:

- A **Producer** column fills `producers` only when the name cell's `(prod. …)`
  didn't already set it — the inline credit is the more specific source.
- **Artist / Credited Artist** columns land in `credited_artists`, which is
  additive and distinct from `featuring`: it is the row's *performing* artist
  (collab-style trackers), not a guest.
- **File Name / Instrumental Name** columns merge into `og_filenames` alongside the
  `OG Filename:` notes convention, deduped.

## parser.py::parse_song_credits — credit delimiters

Trackers write credits in either style — `(prod. X)` (Ye, Kendrick) or `[prod. X]`
(Travis) — and hand-typed sheets mix the two by accident (`[prod. Travis Scott)`
appears three times on the live Travis tracker), so the closer is not required to
match the opener. Every pattern is anchored on its keyword, so bracket support
cannot swallow a version tag like `[V1]` or `[Demo 8]`.

**Multi-line credits stay unparsed on purpose.** A credit whose closer sits on the
next line (`[prod. A,\nB]`) remains an alt title: letting the pattern span newlines
would let an unclosed `(prod. ` swallow real alt-title lines, and it buys exactly
one row across the whole corpus.

## parser.py::apply_badge_tabs — emoji stripping and per-row badges

Highlight tabs routinely prefix **every row** with the badge emoji
(`🏆 Snaily [V2]`). That emoji is part of the raw name, so keying the match on it
matched nothing at all — 0 of 11 rows on Steve Lacy. Both sides of the match drop a
leading badge emoji before the key is computed.

28 of 415 trackers ship a combined `Grails / Wanted` tab, which classifies as the
single kind `grails`. Badges therefore resolve **per row**: the row's own emoji
(`🏆` vs `🏅`/`🥇`/`🥉`), then the block's separator-row label, then the tab kind.
The separator's column varies by tracker (Notes on Steve Lacy and MAVI, Title on
Travis), so it is detected as "exactly one non-empty cell" rather than by position.

## fetcher.py::async_fetch_and_parse — tab selection ranks songs first

Candidates rank by `(has_songs, era_count, song_count)` and selection never
short-circuits on a song-less tab.

A **hub** tab parses to eras with zero songs — it is a page of category
descriptions, not a catalogue. Avicii's is literally named "Main", which is in
`_UNRELEASED_TAB_NAMES`, so under the old "unreleased tab wins with ≥1 era" rule it
won outright and the whole workbook returned 0 of its ~1400 songs.

## fetcher.py::_aggregate_hub_workbook — sibling catalogue tabs

Some workbooks split the catalogue across sibling tabs that each use the ordinary
era grammar and match no keyword set (Avicii: "Avicii Leaks", "Unreleased",
"Instrumentals & Acapellas", "Rare & Lost", "Snippets"). Nothing else picks them up.

The pass is **gated on the hub signal** so healthy trackers never pay for the extra
fetches. An era the artist already has gains a `Section` named after the tab, so the
tracker's own grouping stays visible; a new era is appended whole, since its name is
already unique to that tab. A tab whose songs the winner already has is skipped as a
duplicate view ("Recent"-style tabs).

## fetcher.py::_clean_tab_name — what gets normalized away

The 2026-07-20 sweep found `(WIP)`-suffixed content tabs (`Released (WIP)`,
`Stems [WIP]`, `Art (wip)`) 60+ times across TrackerHub, falling out of
classification entirely — hence the trailing parenthetical/bracket strip. Slash
spacing is normalized so `Grails/ Wanted` matches the `grails / wanted` keyword set.

`_get_unreleased_tab_gid` originally carried its own inline copy of this
normalization and never received the `(WIP)` strip, so `Unreleased (WIP)` (Mag.Lo)
was invisible to it while every other classifier saw it. **One normalizer, used
everywhere** — that is the rule the duplication broke.

`_display_tab_name` is the separate, casing-preserving variant for anything shown to
a user; `_clean_tab_name` lowercases, so running `.title()` back over it mangles real
names (`OG Files` → `Og Files`).

## fetcher.py — content-tab keyword sets

The extra content tabs (Released / Best Of / Worst Of / Stems / other) come from a
2026-07-17 live census of the Ye / Travis / Kendrick / Carti trackers.

Deliberately **not** parsed: `recent` duplicates the main tab; tracklists, album
copies, groupbuys, buys, compilations, tours, samples, `og files (wip)` and
`og snippets` have bespoke non-song grammars; `key`, `socials` and `bpm & keys` are
lookup tables. These live in `_EXCLUDED_TAB_NAMES` as a named set rather than a
comment because the hub aggregation needs the same exclusions.

## fetcher.py — sheet cache size cap

The image cache had a cap; the sheet HTML + parsed-JSON cache did not, so it grew
without bound (a Ye-size tracker is ~10 MB of HTML plus a ~6.5 MB parse). Capped at
1 GB, evicted per hash stem so no orphan `.meta.json` or `.parsed.json` survives
(2026-07-20 review).

## fetcher.py::_infer_artist_name — title suffix stripping

Tracker page titles carry version and visibility suffixes (`Tracker 2.0`,
`Tracker v3`, `Tracker PUBLIC`, `Tracker [Currently in Use]`) that are not part of
the artist name. yetracker.net titles itself `- Google disk` (sic), which is why the
suffix list is compared case-insensitively and includes the misspelling.

## api.py — prewarm loop

Frequently-updated trackers otherwise always serve stale-first once per TTL window:
the first request after expiry gets the stale copy and only *then* triggers a
refresh. The loop revalidates cache entries sitting in the stale-while-revalidate
gap. It **sleeps before its first pass**, so app startup and `TestClient` contexts
never fire network work. `LEAKSHEET_PREWARM=0` disables it (2026-07-20 review).

## api.py — image width buckets

Buckets bound the disk-cache cardinality; clients snap up to the next one. `1600`
was added 2026-07-17 because the old `1280` top bucket sat below iPhone full-screen
width (~1290 px), so Now Playing art was being upscaled on device.

## api.py — CORS is registered last

`add_middleware` makes the **last-added** middleware outermost. CORS must wrap the
rate limiter, or a 429 carries no `Access-Control-Allow-Origin` and the browser
reports an opaque network error instead of a clean 429.

## api.py::_client_ip — X-Forwarded-For is trusted by count only

In production the app sits behind a platform router, so `scope["client"]` is that
router for every request; bucketing the rate limiter on it puts the whole internet
in one bucket. `X-Forwarded-For` is caller-controlled, so it is consulted only when
`LEAKSHEET_TRUSTED_PROXY_HOPS` states how many hops to trust, and the entry is taken
**from the right** — the portion a client cannot forge. A chain shorter than the
declared count means the request didn't arrive through the expected path, so nothing
in it is trusted.

## config.py — the /sheet host allowlist

`POST /sheet` fetches a caller-supplied URL. See
[`docs/reviews/2026-07-27-security-review.md`](reviews/2026-07-27-security-review.md)
for the full finding; in short, without a host check the backend reaches cloud
metadata and RFC1918, and returns any internal page containing a `<table>` as parsed
data.

## models.py — fields kept on the wire with no client reader

`stats` / `stats_raw` / `highlighted_producers` stay in the payload even though no
current client reads them: **the cached bytes ARE the wire bytes**. Dropping a field
from serialization silently invalidates every cached parse, so removals need a
deliberate cache-version bump, not a quiet edit.

## streaming.py — non-streamable hosts are not errors

A link to YouTube, Instagram or imgbb is normal tracker content, not a failure.
`resolve_stream_url` returning `None` means "not playable here", and callers must
treat it as such rather than surfacing an error.
