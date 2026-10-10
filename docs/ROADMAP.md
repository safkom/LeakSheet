# Roadmap

Work we have decided to keep in mind but not schedule. Each item says what would
make it worth picking up.

## Later

### .NET rewrite of the API (ASP.NET Core + AngleSharp)

Not scheduled. Parsing is at most about 2 s of a 10-15 s cold request (the rest is
downloading tabs), and warm requests serve cached bytes with no parse, so a port
buys little today: an estimated 3-5x on parsing, about 1 s off a 12 s cold Ye load.
The cost is a full port of the parser heuristics, the 1,100-test suite and
`docs/decisions.md`.

Revisit when production `sheet_timing` log lines show the `parse` phase taking more
than half of cold-request time, or when the Python runtime itself becomes the
operational problem.

### Stable cover URL in the `/sheet` payload

Google re-signs `docs.google.com/sheets-images-rt/<token>` cover URLs on every
parse, so each era's `art_url` changes on every revalidation. The payload's ETag
changes with it, so clients rarely get a 304 after the first hour (Ye re-downloads
about 1.9 MB gzipped), and the iOS image and colour caches, keyed on the proxy URL,
refill too. The server already keys stored covers by `(tracker, era)`
(`api.py::_era_art_base`); the fix is to put a stable `/image-proxy` reference built
on that in the payload instead of the token URL. It changes the wire format, so it
ships as its own PR with the contract fixture and the iOS update.
