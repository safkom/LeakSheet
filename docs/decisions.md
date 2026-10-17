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

## parser.py::_is_tracker_footer

A footer row stays footer until the next era header, so one false positive drops
every later song in the era. Matching a keyword anywhere in a cell did exactly that
to song rows whose notes mention one in prose: "leaked via the changelog drop", "a
beat idea for TrackerHub" (Trackerism 2 lost 13 of 80 versions). Real footer cells
open with the keyword once emoji and counts are skipped ("🔗 616 Total Links",
"Changelogs", "Want to contribute? …"), so the keyword must start a cell line.
Over a 70-tab corpus the rule changed no other tab's songs.

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

## models.py::parse_song_credits — credit delimiters

Trackers write credits in either style — `(prod. X)` (Ye, Kendrick) or `[prod. X]`
(Travis) — and hand-typed sheets mix the two by accident (`[prod. Travis Scott)`
appears three times on the live Travis tracker), so the closer is not required to
match the opener. Every pattern is anchored on its keyword, so bracket support
cannot swallow a version tag like `[V1]` or `[Demo 8]`.

**Multi-line credits stay unparsed on purpose.** A credit whose closer sits on the
next line (`[prod. A,\nB]`) remains an alt title: letting the pattern span newlines
would let an unclosed `(prod. ` swallow real alt-title lines, and it buys exactly
one row across the whole corpus.

## models.py::_CREDIT_GROUP_RE — wrapped credit lists

This refines the multi-line rule above. A bracketed group spans a newline only where
the line ends with a list separator (`,` or `&`) or the keyword's own dot: that is a
credit list wrapped across `<br>` lines, and an alt title is never preceded by a
dangling separator inside an open bracket. Refusing newlines outright left 2,422 of
54,923 alt titles (4.4%) as credit strings whose long producer or feature list had
wrapped, plus 37 name cells wrapped right after the keyword
(`(prod. \nLondon On Da Track)`). A continuation line that does not follow a separator
still ends the group, so an unclosed `(prod. ` cannot swallow the alt titles below it,
and widening what a group can match is safe because `take_group` hands back untouched
any group whose first part is not a credit keyword.

The spaces around each line break are stripped before matching (`parse_song_credits`),
so every character has exactly one way to match. The earlier form allowed spaces on
both sides of the newline inside the repeat and backtracked exponentially on an
unclosed `(` followed by many `, <newline>` lines (2,000 characters did not finish in
15 s, S5852).

## parser.py::_reconcile_title_misreads — song identity from titles and alt titles

Decided with the user, 2026-09-13, after the iOS version picker showed split songs.

- **Versions group by `song_key`, not the exact title.** Trackers change case and
  punctuation between rows of one song ("Touch The Sky" / "Touch the Sky", 21 songs of
  VULTURES 1 in capitals and in title case). Grouping by the exact string produced Ye
  alone 40 extra songs, while cross-era linking already used the key. The label
  baselines were re-pinned for exactly these merges; version counts did not move.
- **Alt titles link songs; they never merge them.** Trackers cross-list distinct
  released songs as each other's alt titles (Ye's "Self Conscious" and "All Falls
  Down"), so a merge would fuse different songs. Clients link one hop — a song whose
  title matches one of this song's names — for the version picker and search.
- **Slash titles are names, not groups.** "Stay On Em / Precious" is one song with two
  names; "LOVE ME / TOO EASY" is two songs in one file. Each part is a linkable name and
  the row stays its own song.
- **Two misreads are undone using the tracker's own names**, since a single cell cannot
  tell them apart. "(With Child, Stay On Em)" matches the "(with X)" credit form even
  capitalised, and "(With Eminem)" really is one, so it becomes alt titles only when
  every name matches a title or alt title in the same song family (3 cells across 415
  cached trackers). "(Bitch, Don't Kill My Vibe)" is split by the alias-list rule, so
  consecutive aliases are rejoined when the joined text is a song title in the tracker.

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

## fetcher.py::paren-strip-s8786 — the rewrite is not behaviour-preserving

The trailing parenthetical strip in `_infer_artist_name` and `_clean_tab_name` used
`[\(\[][^)\]]*[\)\]]`. SonarQube flagged it super-linear (S8786): with no closing
bracket the scan-to-end restarts from every opening one — 6s on a 32 KB cell, and
tab names come from a sheet whose author is not us. The inner class now excludes
`(` and `[` as well, which makes each start position stop at the next bracket.

That **changes the match** for one shape: a mismatched inner opener. `Name (a [b)`
stripped to `Name` before (the old class scanned straight through the stray `[`)
and strips to `Name (a` now, because the search falls through to the `[b)` group.
Real names carry sloppy brackets but not usually *mismatched* ones, so the trade is
worth it — the divergence is pinned in
`tests/unit/test_linear_fetcher_regexes.py::test_mismatched_inner_brackets_strip_the_inner_group_now`
rather than left to the oracle test, which generates bracket groups atomically and
therefore never produces this shape.

## api.py — image width buckets

Buckets bound the disk-cache cardinality; clients snap up to the next one. `1600`
was added 2026-07-17 because the old `1280` top bucket sat below iPhone full-screen
width (~1290 px), so Now Playing art was being upscaled on device.

## api.py::_client_ip — X-Forwarded-For is trusted by count only

In production the app sits behind a platform router, so `scope["client"]` is that
router for every request; bucketing the rate limiter on it puts the whole internet
in one bucket. `X-Forwarded-For` is caller-controlled, so it is consulted only when
`LEAKSHEET_TRUSTED_PROXY_HOPS` states how many hops to trust, and the entry is taken
**from the right** — the portion a client cannot forge. A chain shorter than the
declared count means the request didn't arrive through the expected path, so nothing
in it is trusted.

## config.py — the /sheet host allowlist

`POST /sheet` fetches a caller-supplied URL. Without a host check the backend reaches
cloud metadata and RFC1918, returns any internal page containing a `<table>` as
parsed data, and its distinct 400/404/502 mappings make it an internal port scanner.

The check covers every tab of a workbook, not just the URL it was handed: a sheet's
page-switcher JavaScript can name absolute tab URLs, which are honoured only for an
allowlisted host or the sheet's own site (`fetcher._build_sheet_html_url`).

`drive.google.com` is not in the seed: it has no `/htmlview/sheet` path, so a Drive URL
would build a request that drops the file id. The image proxy still reaches it through
the `google.com` parent domain.

## config.py::curated_host_allowed — the image proxy does not trust the feed

`/sheet` auto-accepts every host the ArtistGrid CSV lists, so a tracker added to the
community feed works without a redeploy. `/image-proxy` deliberately does not: the
feed is third-party, and that endpoint returns bytes to any origin
(`Access-Control-Allow-Origin: *`). It trusts Google's image CDNs, the built-in seed
and `LEAKSHEET_EXTRA_SHEET_HOSTS` only. Cost: a feed-only tracker whose covers are
self-hosted (`/assets/<sha>.jpg`) shows no art until its host is added to the seed —
which is why `tylertracker.net`, 40 era covers, is in it. Decided 2026-09-13.

## fetcher.py::_get_sheets_client — redirects are not re-checked against the allowlist

`/sheet` checks the allowlist on the URL it is handed and on every tab URL
(`_build_sheet_html_url`), but the client follows redirects without re-checking the
host. The image proxy does re-check. The difference is deliberate:

- A redirect only happens if an allowlisted host sends one. A tracker host that is
  compromised can already serve whatever content it likes under its own URL, so a
  redirect gives it nothing extra.
- `PublicOnlyAsyncTransport` still rejects non-public addresses on every hop, so a
  redirect cannot reach internal services.
- A strict per-hop check would also reject redirects real trackers rely on (`x.net` to
  `www.x.net`, Google sending a private sheet to `accounts.google.com`). Each one would
  need seeding, and nothing short of a live sweep of every tracker would catch the ones
  that were missed.

The remaining gap is an open redirect on an allowlisted host, which would make the
backend fetch a public URL someone else chose. Only the parsed tracker is returned,
never the raw body. Revisit if the image proxy's per-hop check is ever moved into the
transport and can be shared. Decided 2026-09-13, after the branch review.

## fetcher.py::_build_sheet_html_url — advertised tab paths

Some custom tracker hosts (deftonestracker.net, franktracker.net, tylertracker.net)
answer the `?gid=` query form with a ~52 KB shell page that has no `<table>`, so every
tab failed with `NoTablesError` until the fetcher followed the URL the page's own
switcher advertises (`items.push({name: "Unreleased", pageUrl:
"\/htmlview\/sheet\/554276433.html"})`). `_build_sheet_html_url` prefers that path.

Those hosts do emit `gid:` on every switcher entry too, so merging names from the
pageUrl-keyed switcher is a no-op for them. It stays as a cheap fallback for a host
that omits `gid`, which has not been observed.

## models.py — fields kept on the wire with no client reader

`stats` / `stats_raw` / `highlighted_producers` stay in the payload even though no
current client reads them: **the cached bytes ARE the wire bytes**. Dropping a field
from serialization silently invalidates every cached parse, so removals need a
deliberate cache-version bump, not a quiet edit.

## streaming.py — non-streamable hosts are not errors

A link to YouTube, Instagram or imgbb is normal tracker content, not a failure.
`resolve_stream_url` returning `None` means "not playable here", and callers must
treat it as such rather than surfacing an error.

## api.py::middleware-order — CORS is added last

`add_middleware` makes the most-recently-added middleware outermost. CORS must wrap
the rate limiter so a 429 still carries `Access-Control-Allow-Origin` — otherwise a
browser sees an opaque network error instead of a clean 429 response.

## api.py::swr-fast-path — stale-while-revalidate serves raw cached bytes

The fast path returns the cached JSON bytes as-is: no pydantic validation, no
re-serialization, no content re-hash. Those steps cost ~400ms on a 6.5MB artist
payload and were the bulk of warm-request latency.

## api.py::serve-stale-window — a cached tracker is served for 7 days

`/sheet` answers a 304 or serves the stored bytes while the entry is younger than
`SERVE_STALE_TTL` (7 days); a background revalidation starts once it is over an hour
old. Past 24 h the server used to do neither, so a client holding its own copy waited
for a full cold parse anyway: production cold opens took 7.8-20.5 s. The app keeps its
copy for days, so a week of stale-but-instant matches how it is used, and each served
request refreshes the entry for the next one.

`COLLAPSE_GUARD_TTL` (24 h) is the window of `fetcher.py::cache-collapse-guard`. It
is a different question: how long a *larger* old parse outranks a smaller new one. A
week there would freeze a tracker that really shrank (DMCA, restructure) for a week,
while a day still covers a partial fetch landing on a recently refreshed copy. The two
constants are not meant to be equal. A parse that recorded failed tab loads is the
exception: the guard then covers the whole serve window (see `fetcher.py::cache-collapse-guard`).

The window must not prolong content its source has revoked (DMCA). A failed revalidation
only sets the 15-minute backoff, so a deleted or private sheet would otherwise be served
for the whole week. `_background_revalidate` therefore calls `drop_cached_entry` (HTML,
parse and metadata, under the entry lock) when the fetch fails with `SourceGoneError`
(base page 404 or 410) or `AccessDeniedError`. That is a 403, or, for a docs.google.com
sheet, a base page whose redirect chain ended on `accounts.google.com`: Google answers
a private sheet with a redirect to the sign-in page, which comes back as a 200 with no
table (`_raise_if_signed_out`; `_get_capped` keeps the final request so `.url` shows
where the chain ended). Nothing else deletes: a timeout, a connection error, a 429 or
any 5xx (all `NetworkError`), `NoTablesError` (it also covers every sub-page failing
for transport reasons), a disallowed host, and a mirror that redirects elsewhere keep
serving the stale copy. The next request after a drop is a cold parse that returns the
real 400 or 403. `SourceGoneError` subclasses `InvalidURLError` so the cold-path 400 is
unchanged.

## api.py::google-size-suffix-regex — Google image URL suffix grammar

Google's sizing suffix (`=s0-c-rw...`) is a `"="`-prefixed, `"-"`-joined list of
option tokens, not just `w`/`h`/`s`: `no` (don't upscale), `c` (crop), `p` (padding)
etc. all appear with no following digits. So a token is *letters + optional digits*,
not *one of {s,w,h} + required digits* — `_GOOGLE_SIZE_SUFFIX_RE` has to match the
looser grammar or it silently stops resizing.

## fetcher.py::art-tab-identity — an Art-tab cover must be the same picture

The Art tab is a gallery, not a cover list: under an era's name it can hold a single's
art, a sibling era's cover or a promo. Adopting its image by name alone replaced 42 of
Ye's 43 main-tab covers, and Yandhi [V2] showed the "Brothers" single instead of its
lilac CD. The main-tab image is the tracker's own cover but only ~100 px wide; the Art
tab's copy of the same art is ~340 px.

So the cover warm (`api.py::_warm_era_art`) downloads both and stores the Art-tab image only when a 16x16
difference hash of the two is within 40 of 256 bits. Across 91 downloadable pairs from
five trackers (2026-09-27), same artwork measured 0–27 and different artwork 65+; the
one near miss (Ca$ino, 103) is the same photo recropped to a portrait, which rightly
stays on the main-tab image. When either download fails (Ye's proxied tokens are often
already dead) the main-tab cover stays, and an era with no main-tab cover gets no
Art-tab image. The per-era cover slot moved to `v2` at the same time, so name-matched
v1 images are not served again.

The comparison runs after the response, not during the parse: on a slow link to
Google it added 15-20 s to every cold load. Since the payload carries the slot key,
an upgrade changes the slot's bytes, never the payload. If a later Art-tab download
fails, a stored copy of the same picture is kept rather than downgraded.

## api.py::_warm_era_art — covers are downloaded at parse time

Google's `docs.google.com/sheets-images-rt/<token>` cover URLs are signed. A new token
is minted on every page fetch, and it stops working: one fetched directly from Google
still loaded after 28 minutes, and every page served 42 or more minutes after Google
rendered it had dead tokens. A parse, though, is served for up to 7 days and clients
keep it for days. Covers therefore loaded only while the parse was young. On 2026-09-13
production showed no covers for Ye and Travis, while recently parsed Kendrick and Baby
Keem were fine.

After every server-side parse (cold miss, stream, background revalidation), each
era cover is downloaded while its token still works and stored in the image cache under
the exact URL the payload carries (width 0). `/image-proxy` reads that copy before going
upstream, so a cover keeps loading for the image cache's 7-day life.

yetracker.net is a Cloudflare proxy of the Google page with `max-age=3600`, and it
ignores query strings and `Accept-Encoding` when choosing a cached copy. Its tokens are
often dead before we ever parse: a 208-second-old copy worked, a 19-minute-old one did
not. So a cover that fails to download keeps the era's last good copy in its
`_era_art_base` slot. Ye's covers fill in once any parse lands on a young Cloudflare
copy, and stay.

Every parse downloads again and overwrites the slot when it succeeds, so a cover the
sheet changes shows up on the next good parse instead of after the 7-day TTL; the
slot's width thumbnails are dropped when the bytes differ.

## api.py::_era_art_base — covers keyed by tracker and era

A cover's `sheets-images-rt/<token>` URL is reminted on every parse, so nothing in it
is stable. Keying the image cache on it filed the same bytes under a fresh name every
hour and left the LRU to evict the previous one, so a client holding a payload a few
hours old asked for an evicted entry, went upstream, and got Google's 403 on the
expired token — 16% of all `/image-proxy` traffic on 2026-09-21.

`(tracker_url, era_name)` is stable, so the bytes live under a slot derived from it,
with a tiny `imgalias_*` pointer left behind for every URL that has ever named it. Old
payloads keep resolving, and one entry per era replaces one per era per parse.

The payload carries that slot too (`fetcher.py::_finalize`): an `art_url` holding the
re-signed token changed every era's URL, and so the ETag, on every revalidation (all
43 Ye covers between two fetches on 2026-10-10), so clients rarely got a 304. `art_url`
is now `leaksheet:art/v2/<tracker>/<era>?v=<n>`, which every client already passes
opaquely to `/image-proxy`. An `imgsrc_*` pointer holds the slot's latest token URL,
to fill a cold slot, and its picture version `v`. The warm bumps `v` only when a new
download is a different picture, so the payload changes exactly when the cover does. The
sheet-cache eviction skips `imgalias_*` for the same reason, and a cache hit touches
the entry's mtime so a cover still in use is not evicted before stale copies.

## api.py::image-proxy-etag — ETag is scoped to the disk cache

Only width-bounded image-proxy requests are disk-cached, so only they get an ETag —
and it has to reflect a real, still-live cache entry rather than a pure hash of the
request. Otherwise an expired or `/cache/clear`'d entry (or an unsized request, which
is never cached) would revalidate as unchanged forever.

The tag is the cache key plus a digest of the stored bytes, written into the entry's
meta. A tag built from write time instead let a same-second rewrite with different
bytes keep its tag, so a client holding the old image got a 304.

An original that already fits its width bucket is filed under that width too
(main-tab covers are ~100 px and the app asks for 320): otherwise every request
re-read and re-decoded it and it never got a tag. An original that does not decode,
or exceeds the pixel cap, is still never filed under a width.

## api.py::video-codec-regex — codec is the strongest audio/video signal

mp4/mov containers hold audio-only m4a files too, so an ambiguous container without
codec info stays `"unknown"` rather than guessing video. The regex is
substring-tolerant because pillows' codec strings look like `"H.264 High Profile"` or
`"AAC LC"`, not bare codec names.

## api.py::gdrive-interstitial — never proxy HTML as audio

Google Drive can return (and keep returning, even after the confirm-token retry) an
HTML virus-scan interstitial instead of file bytes. `/stream` must not proxy that as
audio — it maps to a 409 so the client falls back to opening the original share link
in a browser instead of playing garbage.

## api.py::mime-sniffing — magic-byte detection of the real container

Some file hosts (e.g. pillows.su) always report `Content-Type: audio/mp4` regardless
of the actual container. Chrome lenient-decodes the bytes; Safari strictly validates
Content-Type against the data and shows "source not supported" when an Ogg file is
served as `audio/mp4`. Because the range starts at byte 0 on a fresh request, the
first 16 bytes are read, the real format is sniffed from magic bytes, `Content-Type`
is corrected, and those bytes are prepended back into the stream so none are lost.

The upstream is read with `aiter_bytes()` and no chunk size: httpx buffers a fixed
chunk size in full before its first yield, which delayed the response headers (the
sniff gates them) by a 64 KiB download. A read may return fewer than 16 bytes, so the
sniff accumulates reads until it has 16 or the body ends; every later chunk is relayed
as it arrives.

## api.py::metadata-deadline — /metadata gives up after 10 s

The shared httpx client is tuned for audio (120 s read timeout), so a provider that
accepts the connection and never answers held a worker for two minutes per call.
`/metadata` bounds all its upstream calls (the metadata fetch and the pillows HEAD
fallback) with one `asyncio.timeout` of 10 s, plus a per-call 5 s connect timeout. A
timeout answers 503 like any other provider failure and logs at WARNING.

## api.py::range-fallback — HTTP 200, not a synthesized 206, when length is unknown

When total size is unknown (or the upstream ignored the Range header), the endpoint
returns the full stream from byte 0 as plain `HTTP 200` rather than faking a `206`.
iOS Safari interprets an `HTTP 200` reply to a Range request as "full file from byte
0" and resyncs; returning partial data with a `200` status would corrupt its
byte-offset-to-timestamp mapping instead.

## fetcher.py::extra-tab-grammars — Released/Best Of/Worst Of/Stems tabs

Added 2026-07-17 from a live tab census of the Ye / Travis / Kendrick / Carti
trackers. Released tabs use the Misc-tab grammar; Best Of / Worst Of / Stems and the
"other" set use the Unreleased-tab grammar — both parse via `parse_misc_tab`'s alias
table.

## fetcher.py::badge-tab-kinds — highlight tabs never become pages

Tab kinds whose entries duplicate main-tab songs with a highlight (⭐/🗑/✨/🏆/🥇) never
become switchable pages. Instead their entries are matched against the era tree and
stamp the corresponding badge onto the existing song — this is what covers trackers
that only mark highlights in a dedicated tab rather than inline.

## fetcher.py::unreleased-tab-priority — main tab is tried first

When discovered, the unreleased/leaks tab is tried before any other GID so that
trackers with a "Recent" landing tab (e.g. Travis Scott 2.0) don't fool the fetcher
into treating the small Recent sheet as the primary data.

## fetcher.py::duplicate-tab-keys — filtering "Recent"-style duplicate tabs

A tab whose songs the winner already has is a filtered view of it, not extra
catalogue. Unidentifiable titles (`"???"`, `"??"`) all key to `""` and are excluded
from the comparison — otherwise a whole tab of mystery tracks would read as one big
duplicate and get dropped.

## fetcher.py::gid-subpage-discovery — per-GID pages need the base page first

Per-GID sub-pages don't embed the workbook's tab listing — only the base `/htmlview`
page does. So a link straight to the Misc/Music-Videos tab (e.g. copied from the
browser while viewing it) can only be told apart from the main tab by asking the base
page. This matters because `parse_sheet`'s Era/Name/Available/Quality columns are
similar enough to the misc-tab grammar that it can extract a plausible-looking but
wrong "eras" list from that tab — which would then short-circuit discovery of the
real main tab and skip parsing it as misc entries entirely. When the GID turns out to
be the Misc/Music-Videos tab itself, the code falls through to full discovery, which
finds the real main tab and parses this one correctly via `parse_misc_tab`.

The same holds for the tabs in `_EXCLUDED_TAB_NAMES` (Recent, Tracklist, …), in both
the gid path and discovery (`_prioritize_gids`). A gid-specific parse is cached under
the gid-less URL every user reads, so a `#gid=<Recent>` link once replaced the whole
catalogue with the Recent subset for 1-24 h; and an excluded tab with more songs than
the real main tab could win discovery outright.

## fetcher.py::gid-fetch-priority — Unreleased first, the rest only if needed

A tab named Unreleased is fetched and parsed on its own first. The remaining GIDs
start concurrently only if it is missing or yields no songs, and are then consumed
in priority order, the rest cancelled once a winner is found. Large trackers expose
15+ tabs; starting them all alongside Unreleased downloaded megabytes that were
thrown away (Ye: 20 requests / 31.8 MB before, 11 / 21.2 MB after, same output).

Winner ranking is the tuple `(songs-or-not, era count, song count)`: a tab with eras
but no songs is a hub/landing page (Avicii's "Main" is a list of category
descriptions) and must never beat a real catalogue tab, however many eras it appears
to have.

## models.py::VERSION_TAG_PATTERN — version tag forms handled

Extracts version tags like `[V1]`, `[V2]`, `[Alt.]`, `[Radio Mix]`, `[MASTER]`. Forms
seen across trackers:

- `V1, V2, v3` — numbered versions
- `V1-V3, V2-V25` — version ranges with known endpoints
- `V1-V?, V2-V?` — version ranges with unknown upper bound
- `V?` — unknown version number
- `Alt, Alt.` — alternate versions
- `Radio Mix, Unfinished` — descriptor versions
- `MASTER, CD VERSION` — recording format versions (Carti tracker)
- `Album, Clean` — release variant versions
- `Song 1, Song 2` — ordered song variants (Carti tracker)

## models.py::_ALIAS_LABEL_RE — stripping the redundant "AKA:" label

Some trackers label the alias line instead of just writing it: Travis uses "(AKA:
iLLamerica)" on 220 of its 259 alias lines. The field IS the alias, so the label is
redundant, and clients that prefix their own "aka" would render it twice — only the
a.k.a. family is stripped, other lead-ins are treated as part of the name.

Parenthetical lines may list several aliases: `"(A, B)"` → two alts. The label is
dropped *before* splitting, so `"(AKA: A, B)"` still yields two clean aliases rather
than one labelled and one bare.

## models.py::_OG_LEADIN_PATTERN — OG Filename lead-in forms

Observed forms the regex has to match:

- `"OG Filename (Metadata): Bitch Im In The CLub NEW"`
- `"OG Filename: Broke My Heart 1"`
- `"OG Filename (?): Blazin' (KW Verse)"`
- `"OG Filenames: Ohh Yeah Tellem RUFF &\nOhh Yeah Tellem RUFF 73.3"` (multi, `&`
  continues on next line)
- `"OG Filename KW - Where Are We Ref (1.15.13)"` (no colon)
- `"OG Filename - Tel Aviv [melody demo 1]"` (dash separator)

## models.py::artist-cleanup — trailing sentence-noise heuristic

Handles cases like `"George Benson and the Common vs. Kanye…"` where the capture ran
into prose. The `"and"` strip is a heuristic that may affect compound band names;
`"&"`-joined names are unaffected.

## parser.py::ERA_STATS_PATTERN — era stats row forms

Matches "0 OG File(s)1 Full0 Tagged2 Partial..." and "1 Total Full0 OG File0 Partial
/ Cut0 Snippet3 Unavailable" (Carti), plus variant formats found across 400+
trackers: "3 of Leaks\n0 of Snippets" (Billie Eilish), "0 Streaming | 1
Off-Streaming" (Joji), "27 tracks" (Gucci Mane, Chief Keef), "0 Released | 1 Deleted
| 5 Lost" (XXXTENTACION), "5 Leaks\n2 Snippets" (common template variant).

## parser.py::_DISCOGRAPHY_STATS_PATTERN — discography stats need two pairs

Two unrelated vocabularies appear in the era-stats cell, and a tracker uses one or the
other: leak-status (`45 Full / 3 Partial / 70 Unavailable`) and discography
(`18 Total / 4 Singles / 7 Album Track(s)`). With only the first recognised, every
discography-style era header failed `_is_era_header` and the era — cover art, timeline,
description — was dropped, its songs glued onto the previous era: 267 era headers
across 34 of 400 cached tabs.

They are not matched the same way. One leak-status pair identifies a stats cell ("5
Full" is never anything else). Discography words are ordinary English that appears in
era NAMES ("2009 Album", "1977 Sessions", "38 Special Sessions"); matching those on one
pair turned 86 Bonnie McKee song rows into empty eras. A real discography block always
states several counts, so it needs `_MIN_DISCOGRAPHY_PAIRS` (two).

## parser.py::broken-stats-formula — spreadsheet errors are never content

A broken formula shows as `#REF!`, `#N/A` and the like. A `#REF!` in the era-stats
column hid every era header on the Future tracker (2026-08), collapsing it into one era
literally named "#REF!". `_is_era_header` therefore still accepts a stats cell holding
an error — it carries no evidence either way — when another cell supplies the era name
or art, and `_looks_like_era_name` rejects an error value as a name: as an era, the
abbreviated-era-name rule would absorb every later era into it.

## parser.py::is_song_tab — reject tabs on positive signatures only

Glossaries, artwork indexes, interview logs, setlists and BPM/key references are
ordinary tabs, and the song parser does not fail on them — it emits plausible junk. The
Car Seat Headrest interview tab produced 146 "songs" titled with interview headlines,
because no Name column was detected and `name` fell back to positional index 1.

Rejection needs a POSITIVE signature (artwork or interview columns, or a header that
resolves to exactly `{available_length, quality}`, the glossary every template ships).
Absence is not evidence: "no Name column" destroyed De La Soul (205 songs under an
unlabelled header) and Overlord's Lil Uzi Vert discography (283 songs under "Project &
Track Title"); "neither Name nor Era" then destroyed headerless tabs — BIG L (21) and
Labrinth (169) start with data at row 0, resolve to an empty map, and parse correctly
through the positional fallback. Artwork needs two column signs because a lone "Image"
column also appears on physical-release tabs, which are real song content.

## parser.py::digit-leading-era-names — stats vs. real era names

Digit-leading lines are only stat-like when a stats keyword follows or the line is a
bare number — era names DO start with digits ("38 Baby 2 [V1] / …", "808s &
Heartbreak"-era variants; 2026-07-20 review, NBA Youngboy). Without this exception, a
sparse header whose only text cell is such a name is rejected outright.

## parser.py::era-key-shadowing — fallback dict vs. authoritative dict

Comma-separated alias lists ("Mollyworld, Balaclava Era") register each alias in the
fallback dict only — same shadowing rationale as slash-separated parts: a genuine
standalone era declared elsewhere still claims the primary key.
Every era-header site (stats-bearing, stats-less, multi-line and name-column) follows the
same rule: it passes the fallback dict, so no header's slash or alias part claims a primary key.

## parser.py::name-cell-image — album art vs. image-based era name

If the name cell has usable text alongside an image, the image is album art. If the
cell has NO text (an image-based era name, like Carti's Narcissist logo), the image
IS the era name, not art.

## parser.py::backfill-era-priority — image-only header backfill ordering

When the current era needs a name backfill (image-only header), a song row is
assigned to it *before* the normal lookup — otherwise fuzzy matching can steal it for
a similarly-named era (e.g. WLR [V3] swallowing WLR [V4] songs because version tags
are stripped).

## parser.py::abbreviated-era-names — song rows using different era abbreviations

If a song row has actual metadata (links, quality, etc.), it's assigned to
`current_era` over creating a new one — this handles trackers where song rows use
different era abbreviations than the header (e.g. Pop Smoke, Jay-Z). The row's era
name variant is registered into the fallback dict, not the authoritative one, so a
genuine era header with the same name declared later still claims the primary key —
otherwise this speculative mapping would starve that real era.

## parser.py::sub-era-header — sub-era header vs. section label

Detected when `era_col` is empty but `name_col` has text, with very few filled
cells. In Yung Lean, "Before Unknown Death" appears in the name column as an era
header; in other trackers the same shape is a section label. Travis Scott's era
header rows have the era name on line 1 and a year range on line 2 via a `<br>` tag
(`"The Graduates\n(2007 - 2009)"`); sub-section rows ("Other Media", "Production")
only ever have a single-line label with no embedded newline — that's the
disambiguator.

## parser.py::section-label-alias — registering a section label as an era alias

Song rows that reference a section label in their era column should route to that
section instead of fuzzy-matching an unrelated era (e.g. "Drake vs. Kendrick Lamar"
fuzzy-matching to "The Kendrick Lamar EP" due to shared words). Registered into the
fallback dict — consulted before fuzzy matching but after the authoritative
`era_by_key` — so a real era header sharing this name (declared later) still wins the
primary key. A section label must never starve a genuine era (e.g. the "War" label
inside DONDA 2 vs. the standalone WAR era).

## parser.py::positional-fallback — blank era column, current era exists

Many trackers (Glaive, etc.) leave the era column blank for song rows and only fill
it for era headers. If the row has enough filled cells to look like a song, it's
parsed and assigned positionally to whatever era is currently open.

## parser.py::merge-stub-eras — merging 0-song stub eras

Handles trackers like Travis Scott 2.0, where full era names in header rows differ
from the abbreviated era names used in song rows (e.g. "Birds In The Trap Sing
McKnight" vs. "Birds") — a name-column era header creates a 0-song stub era that then
gets merged into its adjacent songs-bearing era.

## parser.py::_STATS_LIKE_ERA_RE — shape-based stats cell recognition

Matches "1 Mixtape Tracks", "0 Project(s)", "99 tracks" — counted-stats cells whose
vocabulary a fixed keyword list doesn't carry. Recognised by shape (`^\d+\s+\S`) so
the parser doesn't need every tracker's noun. Only ever used together with "the title
names a known era", which is what keeps real era names starting with a digit ("50
Cent Presents…") from matching as stats.

## parser.py::grails-wanted-separator — combined-tab section separator

Combined "Grails / Wanted" tabs use a lone non-empty cell to divide the two halves.
The column varies (Notes on Steve Lacy/MAVI, Title on Travis), so the match is on
"exactly one non-empty cell in the row" rather than a fixed column.

## parser.py::badge-tab-structural-rows — real row vs. structural row in badge tabs

Per-track data is what separates a real row from a structural one (section header,
bare label). Two fields are deliberately excluded from that check: `notes`, because
era headers carry prose too and some tabs (Fakes) have notes as their only field; and
`entry_type`, because Baby Keem's Released header row puts era prose in its Type
column.

Two more era-header shapes the primary stats check can't see: an EMPTY era cell with
the era name in the title (Travis "Released"), or a counted-stats cell whose
vocabulary isn't in the fixed list ("1 Mixtape Tracks", Baby Keem). Both share one
shape — the title names an era that OTHER rows in this tab put in their era column,
while this row does not carry that era itself.

The extra safety condition: "Purple Swag (Chopped Not Slopped)" keys to its own era
once `_era_match_key` drops the parenthetical, so it needs either no track data at
all, or an era cell that is visibly a stats block rather than an era name — otherwise
a real song could be misread as a header. Header rows sometimes spill their prose
into a mapped column (Baby Keem's lands in Leak Date), which is why the stats shape
is checked structurally and not against a keyword list.

Bare label rows with nothing at all ("Projects" and "Features" between Travis's
release groups, "Music Videos" atop Chief Keef's) are judged on MAPPED fields — these
rows often do have text, but in columns this tab doesn't read. `entry_type` counts as
content here even though the header test above ignores it — a row whose only field is
"Freestyle" is still an entry, not a structural row.

## streaming.py::imgur-cdnurl-guard — the cdnUrl field is not trustworthy

imgur.gg returns a `cdnUrl` in its file-metadata JSON that is then fetched
server-side. That value is attacker-influenceable if the imgur API is ever
compromised or cache-poisoned, so it can't be trusted blindly: a crafted `cdnUrl`
pointing at a cloud metadata endpoint (169.254.169.254) or an internal service would
turn this proxy into an SSRF pivot. HTTPS is required and any destination resolving
to a non-public address is rejected. (The krakenfiles path is already constrained by
`_KRAKEN_CDN_AUDIO_PATTERN`.)

## streaming.py::scraper-read-cap — gzip-bomb protection

Scraped HTML pages (krakenfiles view page, gdrive interstitial) only ever carry the
CDN URL / confirm form near the top. httpx transparently decompresses response
bodies, so an uncapped read of a gzip-bombed page could unpack to hundreds of MB and
OOM the worker — reads are capped at 512 KiB decompressed.

## streaming.py::gdrive-url-forms — id extraction strategy

`drive.google.com/file/d/{id}/...` has the id captured directly; the `open?id=...`
and `uc?id=...` forms are handled via query-string parsing in `_extract_gdrive_id`
instead, since the id can appear alongside other params in any order there.

## streaming.py::url-pattern-case — links match in any case

Hosts and path keywords (`/f/`, `/song/`, `/view/…/file.html`, `/u/`, `/file/d/`, drive
`/open` and `/uc`) match case-insensitively, so a tracker's `HTTPS://Pillows.SU/F/x` plays.
File ids keep their case: the providers' ids are case-sensitive.
Drive's `/open` and `/uc` forms compare the netloc, not the hostname, so a port or
userinfo is refused there exactly as in the regex forms.

Folding is ASCII-only (`re.ASCII`). Under Unicode ignore-case `ſ` and the Kelvin sign
would pass for `s` and `k` in a host. Foundation does fold them, so Swift's
`StreamResolver` refuses a non-ASCII authority. `tests/parse/test_link_rule_contract.py`
pins the Python and Swift rules together.

## streaming.py::no-metadata-hosts — kraken and gdrive have no metadata API

krakenfiles has no metadata API (the view page only yields a filename); clients fall
back to player-derived format info for kraken links. drive.google.com has no
metadata provider either (Drive exposes no public file-metadata API without auth).

## streaming.py::gdrive-interstitial-bypass — virus-scan interstitial retry

Large or unscanned files served from `drive.google.com/uc?export=download` return an
HTML "Google Drive can't scan this file for viruses" confirmation page instead of the
file bytes. The page contains a hidden-input form that posts (as a GET) to
`drive.usercontent.google.com/download` with fields `id`/`export`/`confirm`/`uuid`;
retrying against that URL once yields the real file. If the retry *also* comes back
as HTML, the code gives up rather than ever proxying HTML bytes to the client as if
they were audio.

Redirects are constrained to a fixed, literal two-host allowlist — the same
defense-in-depth spirit as the imgur cdnUrl guard, but here the hosts are hardcoded
(never attacker-influenceable) so a simple membership check on the final resolved URL
is sufficient. Large public files are frequently served from Google's storage CDN
(`*.googleusercontent.com`); still Google-controlled, so redirects there are
accepted, anything else stays rejected.

The dedicated gdrive path also allows `video/*` and `application/octet-stream`
(Drive's generic type for many audio files) in addition to `audio/*`, and lets 403
(permission required) pass straight through instead of becoming a generic 502.

## config.py::COLUMN_ALIASES — dedicated credit columns

User-confirmed mappings from the 2026-07-20 tracker sweep: a dedicated `producer`
column fills `SongVersion.producers` only when the name-cell `(prod. …)` credit
didn't already set it (the name-cell credit wins on conflict). Dedicated `artist`
columns land in the additive `credited_artists` field — the row's performer, not a
feature — so they never overwrite the primary artist.

## config.py::COLUMN_ALIASES — unmapped headers

Headers seen in the 2026-08-26 corpus sweep and deliberately left unmapped, recorded so
the next sweep does not re-litigate them (counts are workbooks):

- `Image`, `Project Type`, `Art Type`, `Use`, `Designer`, `Cover Art` — art-tab
  headers. `is_song_tab` already rejects those tabs; they show up only because the tab
  is scanned before it is rejected.
- `Engineer` (6), `Recording Location` (4), `Creator` (5), `Platform` (3),
  `File Type` (3), `Origin` (2), `Price` (2) — real data with no field to hold it. Each
  costs a model field plus a decode on every client for a handful of workbooks; revisit
  if a sweep shows them spreading.
- `#` (3), `#:` (3) — track-number columns. Binding one to `name` is how Overlord's Lil
  Uzi Vert tracker came to have 281 songs called "1", "2", "3" (see
  `parser._infer_name_column`).
- `Tracklist` (12), `Album` (5), `Release` (5), `Category` (8) — ambiguous. "Album" is
  an era on a discography tracker and a track's parent release elsewhere, and binding
  `era` wrongly is expensive; unmapped until one meaning is shown to dominate.

---

## parser.py::art-cover-column — the cover test reads the Project Type column

Tracker Notes prose mentions "cover" constantly (626 rows on the Ye art tab), so
matching `\bcover\b` against the whole row fired almost everywhere and the era's
*first* row won regardless of what it depicted. The test reads the Project Type
column only.

## parser.py::art-type-column-priority — "Project Type" beats "Art Type"

`_ART_TYPE_HEADERS` is an ordered tuple, not a set, and the header scan takes the
best-ranked match rather than the leftmost one.

An art tab can carry two type columns: **Art Type** holds the medium (Digital /
Scan / Photo / Recreation) and **Project Type** holds the role (Front Cover /
Back Cover / Promo Art / Booklet / Concept Art). Only the role column can
identify a cover. On the Ye tab the medium column comes first, so first-match-wins
bound `type_idx` to it, `_COVER_RE` never matched a single row, and the cover
preference documented above was dead for **every era on every tracker with both
columns** — each era silently fell back to whichever artwork happened to be
listed first. Found 2026-08-26 by comparing rendered era art against the tab.

## parser.py::art-version-keys — art keys keep [V1] and (2018)

`_era_match_key(..., keep_discriminators=True)` preserves a version tag and a
parenthetical; the default still strips both, because song rows reference their
era without them.

An Art tab names each sibling's cover explicitly — `Donda [V1]`, `Donda [V2]`,
`Donda [V3]`, `Good Ass Job (2018)` — but the stripped key collapsed all of them
onto one entry, first-wins, so every version wore the first version's artwork.
On Ye that was 6 eras (Donda V2/V3, Yandhi V2, DONDA 2 V2, BULLY V2, Good Ass Job
2018); Donda V3's real cover is the plain black sleeve, and it was showing V1's
orange artwork instead.

`parse_art_tab` files every entry under BOTH the discriminating key and the
stripped one (first versioned entry wins the stripped slot), and `_era_art_candidate`
tries the discriminating key first, then the stripped one, for the era name and
then each alt name. That keeps two older shapes working: an Art tab that tags its
rows serving an era that doesn't (`Donda` → V1's cover), and an era that tags
itself against an Art tab that doesn't. A stripped key standing in for a sibling
version is never a candidate for a versioned era. Every candidate is still only
adopted when it is the same picture as the main-tab cover
(fetcher.py::art-tab-identity).

---

## fetcher.py::cache-collapse-guard — a partial parse must not replace a good one

`_set_cached_parsed` refuses to overwrite a cached parse when the new one
carries less than `CACHE_COLLAPSE_RATIO` (0.8) of its tracks. The result is
still returned to the caller; only the write is skipped.

A partial fetch — some tabs short, or a sibling hub workbook that failed to
load — parses cleanly and is indistinguishable from a healthy result, so it was
cached like any other and then kept alive by stale-while-revalidate. Production
served the Ye tracker at **5,817 tracks across 36 eras** for exactly that
reason, with era order scrambled because the partial merge appends sibling
tabs in completion order, while a fresh parse of the same URL on the same code
gave **9,382 across 44** in sheet order. Nothing surfaced it: the counts looked
plausible, no error was raised, and only a forced refresh cleared it.

The guard is deliberately one-sided. Growth always writes, a modest shrink
always writes (trackers do lose tracks — DMCA, restructures), and the old copy
wins only while it is still inside `COLLAPSE_GUARD_TTL` (24 h, deliberately shorter
than the 7-day serve window, see `api.py::serve-stale-window`); past that a
genuinely shrunken tracker recovers on its own instead of being frozen for days.
The refusal is logged at WARNING so a systematically broken tab is visible rather
than silent — which was the real defect here.

An empty parse (zero versions) is refused before the no-entry early return, so the
discovery fallback and the base-page branch are covered with the rest: cached, an
empty result was served as a hit for an hour and then cached again by the app. It is
refused even over an entry past `COLLAPSE_GUARD_TTL`.

`/sheet` answers an empty parse with 404 "No songs found in this tracker.", like
`NoTablesError`, on the JSON and the NDJSON response alike: a 200 put an empty tracker in
the app's cache and Recents, while the app caches no error. A parse that also recorded
failed tab loads is a 503 instead: it is likely transient, and on a 5xx the app falls back
to its own copy, which a 4xx forbids. An empty entry already on disk (`total_versions` 0 in its meta) is neither served
nor 304'd. The base-page branch, like the gid path, returns only a parse with songs; a
hub table on the base page falls through to discovery.

A partial load alone is never refused: a tab that is permanently missing would
otherwise keep its tracker out of the cache for good, and a large drop is the ratio's
job. It does widen the ratio's window: a parse that recorded failed tab loads and shrank
past the ratio is refused over any entry younger than `SERVE_STALE_TTL`, because those
entries are served and a partial revalidation of a 1-7 day old copy would replace a good
one. Past the serve window the entry is no longer served, so the partial parse is written
and a tab that fails for good cannot freeze its tracker. `PhaseTimer.tabs` records each tab page by gid (gid, secondary and hub fetches) and
the last fetch of a gid wins: a hub sibling is fetched by the discovery probe and again by
the merge, and the merge's page is the one whose songs are kept. `_parse_once` copies the
shared parse timer's `tabs` into each caller's timer, as it does the phases. One WARNING
per parse (also before the fallback parse) and the `failed_tabs=failed/total` field on
`sheet_timing` report it.

## api.py::payload-duplication — measured, kept on purpose (2026-08-26)

A full Ye response is **11.56 MB raw / 1.86 MB gzipped**. Two parts of it are
duplication, and the deep review measured both before deciding to keep them.

`Artist.misc_entries` (0.36 MB, **3.13%**) repeats the Misc and Music Videos
entries that are already inside `tabs`. It exists so a client that predates
`tabs` still finds those entries, and iOS still falls back to it when `tabs`
is empty. Removing it needs either a request flag or a client-version signal,
and the `/sheet` warm path serves the parsed-cache file's raw bytes verbatim —
so a per-request variant means either a second cache entry or post-processing
the payload on every hit. Three percent does not buy that, and it breaks
anyone on an older build.

`Song.dict`'s convenience fields — `available_length`, `quality`,
`track_length`, `leak_date`, `file_date` lifted from the primary version
(0.50 MB, **4.34%** across 4,117 songs) — are read by exactly one place:
`web/FavouritesPanel.vue` reads `song.quality`, and falls back to
`versions[0].quality` when it is absent. Dropping the four nobody reads is
worth ~3.5% raw / ~2.9% gzip.

Both removed together: 11.56 -> 10.68 MB raw (-7.6%), 1.86 -> 1.74 MB gzip
(-6.2%).

Rejected at that price. The review's own rule was "under ~3% is not worth a
back-compat cost", and neither piece clears it on its own. Revisit if a client
ever needs to fetch a tracker on a metered connection, where the honest fix is
a slimmer *shape* — versions without their notes prose, which is 1.47 MB by
itself — rather than shaving duplicates.

## models.py::EraStats — parsed, served, and not yet shown (2026-08-26)

`Era.stats` (the maintainer's own per-era counts), `Era.stats_raw`,
`Era.highlighted_producers` and `MiscEntry.section` are parsed and sent, and no
client decodes them. That is a gap, not a defect: displaying an era's stated
counts beside the app's derived ones is a design question, not a fix, and
`MiscEntry.section` has no display site at all today because badge tabs are
annotation sources rather than pages.

They stay on the wire regardless — `Era.dict` already documents why: the
`/sheet` warm path serves the parsed-cache bytes as the response, so excluding
a field from the response also strips it from the cache round-trip and blinds
the starved-era health check.

## Backend language — staying on Python

Assessed 2026-07 against Rust and Bun. The numbers that decided it: a Ye-sized parse
(11.7 MB HTML) takes about 0.9 s through lxml, whose table extraction is already C; a
warm cache hit is about 2 ms; and a cold request is dominated by downloading Google's
HTML, which no runtime shortens. A rewrite would trade a network-bound problem for the
loss of a mature parser and its ~800-test suite. Revisit only if parse time, not fetch
time, becomes the measured bottleneck.

Re-assessed 2026-09-13 against production: a cold Ye request took 15.3 s, of which about
5.4 s was CPU (parse, merge, three serializations) and the rest was downloading tabs. The
fix was in the request plan, not the language — fetching the Unreleased tab first and
skipping tabs it already covers took Ye from 20 requests (31.8 MB) to 11 (21.2 MB) with
byte-identical output, and serializing once per miss removed two of the three
serializations. The remaining wait is now shown rather than hidden: `/sheet` streams
NDJSON progress lines to clients that ask for `application/x-ndjson`.

**Re-assessed 2026-10-16 (ADR, accepted): stay on Python 3 + FastAPI + gunicorn/uvicorn-worker
+ lxml.** Measured on ten trackers loaded cold one at a time: wall time 1.6-11.8 s, of which
parsing (`parse` + `misc_parse` + `art_parse` + `hub_parse`) was 0.05-1.5 s. Production app cold
opens took 7.8-20.5 s with parse at 59-403 ms. On the 20 largest corpus tabs, `extract_table`
is 55 % of parse time, mostly building one `_Cell` per `<td>` (~1.1 M per pass). Python 3.14
parsed them 5 % faster than 3.11, which is inside run-to-run noise.

| Option | Cold-load gain | Cost |
|---|---|---|
| Keep Python/FastAPI | none | none |
| Litestar, plain Starlette, Granian | none measurable at ~50 loads/day | migration churn |
| Go, ASP.NET Core, TypeScript, Rust | at most the parse share (≤1.5 s of 12 s) | port ~3,000 lines of heuristics and ~1,200 tests; per-worker state redesign |
| selectolax instead of lxml | only part of the 55 % in `extract_table` | 1.0 API break (2026-10); parity risk |

Cold loads wait on Google, so the levers are the request plan and the data source (see
fetcher.py::data-source), not the runtime. Move off 3.11 before its security support ends in
2027-10 for the support window, not for speed. Revisit a port when `sheet_timing` shows parse
above half of cold time, or the Python runtime itself becomes the operational problem.
Research: `docs/reviews/2026-10-16/` (local, untracked).

## fetcher.py::data-source — htmlview stays; Sheets API v4 is the candidate (ADR, proposed)

Measured 2026-10-16 on three public workbooks, per path, against the htmlview HTML:

| | htmlview (today) | XLSX export | Sheets API v4 `spreadsheets.get` |
|---|---|---|---|
| Requests, time | 12-22, 12-24 s sequential | 2, 10-14 s | 1, 1.3-4.2 s |
| Bytes on the wire | 0.75-1.3 MB | 83-108 MB (embeds media) | 0.7-1.2 MB gzip (13-34 MB JSON) |
| Hyperlinks | baseline | loses secondary links in multi-link cells | all on 2 of 3; 5 URLs missing on the third |
| Era covers (in-cell images) | 47 / 262 / 382 | 0 / 262 / 381 | none: v4 has no image field |
| Notes, conditional colours | no | notes yes, conditional colours no | both |
| Refusals | none | 401 when the owner disabled downloads | none |

XLSX is rejected: too large, refused by download-disabled sheets, and it drops links. The API
is the fastest and richest path for cell data, but it cannot see covers. It needs an API key
(anonymous calls get 403) with quotas of 300 reads/min per project and 60 per user, no daily
cap. Mirror domains (yetracker.net, `*tracker.net`) are not Google URLs, so the API cannot read
them. The decision is to keep htmlview, and prototype a hybrid behind the existing cell
model: the API for every tab's cells and links, htmlview only for tabs that carry covers. That
cuts a cold load from 8-16 Google page fetches to one API call plus one or two pages. Adopt it
only if the hybrid's output matches htmlview on the accuracy labels and the yetracker diff.

## api.py::upstream-503 — proxy failures answer 503, not 502

Cloudflare replaces an origin's 502 (and 504) with its own HTML error page, so a
proxy's JSON `detail` never reached a client: `/stream` for a pillows outage arrived
as Cloudflare's page. `/sheet` already answered 503 for this reason; `/stream`,
`/image-proxy` and `/metadata` now do too. The relayed 404, 409 and 429 stay.

An upstream 4xx is the host answering about one file (451 takedown, 401, 403), not a
proxy failure: `/stream` relays it as the same code, and only 5xx and transport errors
are 503. A 503 says "try again later" about a file the host refused for good, and hides
the code from the client.

## api.py::non-media-415 — /stream refuses a body that is plainly not media

Tracker links sometimes point at a PDF, an archive or an image. Drive labels them
`application/octet-stream`, which passes the content-type gate, and the sniff then
fell back to `audio/mpeg`: production relayed a PDF as `206 audio/mpeg`. When the
first chunk matches no audio or video signature but does match a known document,
archive, image or HTML one, `/stream` answers 415 instead.

## host_health.py — per-provider stream health, shared through one file

A provider that is down (froste on 2026-10-10) made every play attempt wait out a
connect timeout before failing, and AVPlayer makes several attempts per track. Each
/stream outcome now feeds a per-provider state in `CACHE_DIR/host_health.json`,
written under a flock so all gunicorn workers share it. A connect-level failure marks
a provider down at once; a 5xx or read timeout needs 3 failures within 120 s across
2 links, so one broken file never takes a host down. A down provider gets an instant
503 with `Retry-After: 60`. One worker (non-blocking probe lock) re-probes every 60 s
with the recent failing links (`bytes=0-0`); any answer, a 404 included, means up.

Only /stream feeds it: on that day pillows' metadata API was healthy while its stream
endpoint returned 500, so metadata outcomes would mislabel the stream path. Links are
never crawled: tens of thousands of probes would invite rate limits and bans.

Probe links can be permanently broken files, so the down state also expires: 300 s
after it was set (`HALF_OPEN_AFTER_S`, `retry_at` in the shared file, so all workers
agree), `/stream` lets requests through. A success marks the provider up; a failure that
`record_failure` records restarts the 300 s. `/hosts` says "down" until a success.
A body that is not media (`NonMediaError`, the 415 sniff) is the host answering with a
bad file: it counts as a success, never toward down, in `/stream` and in the probe.
That includes the resolver steps: a kraken page with no audio URL and an imgur API
answer without `cdnUrl`. A 4xx from the kraken page or from every imgur host is an
`UpstreamStatusError` like one from the file itself. A bare ValueError from a resolver
still counts as a soft failure: those wrap transport errors, upstream 5xx and the SSRF
pre-flight.
