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
