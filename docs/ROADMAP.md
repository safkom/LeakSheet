# Roadmap

Work we have decided to keep in mind but not schedule. Each item says what would
make it worth picking up.

## Later

### .NET rewrite of the API (ASP.NET Core + AngleSharp)

Not scheduled. Measured 2026-10-16, parsing is at most 1.5 s of a 1.6-12 s cold request
(the rest is downloading tabs), and warm requests serve cached bytes with no parse, so a
port buys little today: an estimated 3-5x on parsing, about 1 s off a 12 s cold Ye load.
The cost is a full port of the parser heuristics, the ~1,200-test suite and
`docs/decisions.md`. The full comparison is in `docs/decisions.md` (Backend language).

Revisit when production `sheet_timing` log lines show the `parse` phase taking more
than half of cold-request time, or when the Python runtime itself becomes the
operational problem.

### Open findings from the 2026-11-10 review

Confirmed in code, not yet fixed. Each needs a live check or an owner decision first.

- **Favourites keyed by tracker URL** (`FavouritesManager.key`): the slug key breaks when
  the pinned name falls out of Recents. Needs a migration of stored favourites.
- **Contract fixture that can fail**: most optional fields in `contract.json` are null, so a
  renamed wire key decodes to nil unnoticed. Populate every field and assert the key paths.
- **Open requests during a load** (`TrackerLoader.load` refuses silently) and **deep links
  behind an open sheet** (`ContentView.consumeDeepLink`).
- **Pull-to-refresh resets search, filters and expansion** (`ArtistView.refresh`).
- **Mac inspector selection** goes stale after search, filter or refresh; the Now Playing
  window gets no `ArtistViewModel`.
- **Stream pool isolation**: `/metadata` and the resolvers share the 50-connection stream
  client, so slow stream readers can starve them.
- **Harvested tracker hosts are per worker**: persist the list in the cache directory.
- **Failed stream halts auto-advance** (`AudioEngine` `.failed`): skip to the next item, or
  keep stopping. Owner decision.

Pick these up when a user reports one, or as the next fix batch.
