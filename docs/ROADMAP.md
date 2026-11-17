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
- **Pull-to-refresh resets search, filters and expansion** (`ArtistView.refresh`).
- **Mac Era inspector** keeps a stale era after leaving it (`MacUIState.selectedEra`).
- **Stream pool isolation**: `/metadata`, the resolvers and the health prober's resolve step
  share the 50-connection stream client, so slow stream readers can starve them.
- **Harvested tracker hosts are per worker**: persist the list in the cache directory.
- **Failed stream halts auto-advance** (`AudioEngine` `.failed`): skip to the next item, or
  keep stopping. Owner decision.
- **imgur answer without `cdnUrl`**: `docs/decisions.md` (host health) says it counts as the
  host answering; the code counts a soft failure. Pick one. Owner decision.
- **Same-named songs in one era** resolve to the first in the details sheet
  (`ArtistViewModel.resolvedSong`), and the era sheet looks its era up by name.
- **Image cache orphans**: eviction sweeps `img_*.bin` only, not metas or temp files.
- **Apple Music library tally on the main actor** on every tracker-list load
  (`MusicLibraryService.libraryArtists`).
- **A cover that times out is missed for the session** (`ImageCache.loadImage`).

Pick these up when a user reports one, or as the next fix batch.
