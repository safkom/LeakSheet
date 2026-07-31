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

## api.py::middleware-order — CORS is added last

`add_middleware` makes the most-recently-added middleware outermost. CORS must wrap
the rate limiter so a 429 still carries `Access-Control-Allow-Origin` — otherwise a
browser sees an opaque network error instead of a clean 429 response.

## api.py::swr-fast-path — stale-while-revalidate serves raw cached bytes

The fast path returns the cached JSON bytes as-is: no pydantic validation, no
re-serialization, no content re-hash. Those steps cost ~400ms on a 6.5MB artist
payload and were the bulk of warm-request latency.

## api.py::google-size-suffix-regex — Google image URL suffix grammar

Google's sizing suffix (`=s0-c-rw...`) is a `"="`-prefixed, `"-"`-joined list of
option tokens, not just `w`/`h`/`s`: `no` (don't upscale), `c` (crop), `p` (padding)
etc. all appear with no following digits. So a token is *letters + optional digits*,
not *one of {s,w,h} + required digits* — `_GOOGLE_SIZE_SUFFIX_RE` has to match the
looser grammar or it silently stops resizing.

## api.py::image-proxy-etag — ETag is scoped to the disk cache

Only width-bounded image-proxy requests are disk-cached, so only they get an ETag —
and it has to reflect a real, still-live cache entry rather than a pure hash of the
request. Otherwise an expired or `/cache/clear`'d entry (or an unsized request, which
is never cached) would revalidate as unchanged forever.

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
first chunk is read, the real format is sniffed from magic bytes, `Content-Type` is
corrected, and the chunk is prepended back into the stream so no bytes are lost.

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

## fetcher.py::gid-fetch-priority — concurrent fetch, priority-ordered consumption

Every GID fetch starts concurrently, but results are consumed in priority order:
each is parsed as it lands and the rest are cancelled once a winner is found. Large
trackers expose 15+ tabs; the prioritized (unreleased) tab is almost always index 0,
so eagerly completing every fetch would download megabytes that are thrown away.

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

## models.py::ALIAS_LABEL_RE — stripping the redundant "AKA:" label

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

## parser.py::digit-leading-era-names — stats vs. real era names

Digit-leading lines are only stat-like when a stats keyword follows or the line is a
bare number — era names DO start with digits ("38 Baby 2 [V1] / …", "808s &
Heartbreak"-era variants; 2026-07-20 review, NBA Youngboy). Without this exception, a
sparse header whose only text cell is such a name is rejected outright.

## parser.py::era-key-shadowing — fallback dict vs. authoritative dict

Comma-separated alias lists ("Mollyworld, Balaclava Era") register each alias in the
fallback dict only — same shadowing rationale as slash-separated parts: a genuine
standalone era declared elsewhere still claims the primary key.

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

## parser.py::STATS_LIKE_ERA_RE — shape-based stats cell recognition

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
