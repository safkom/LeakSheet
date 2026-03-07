# Design: Art Tab High-Quality Images + Header Field Aliases

**Date:** 2026-03-07

## Problem

1. Era cover art images are low quality — they come from embedded Google Sheets thumbnails (often `lh7-rt.googleusercontent.com` which cannot be resized). Spreadsheets have a dedicated "art" tab with higher-quality versions of the same images.
2. Some tracker spreadsheets use header column names not yet in `COLUMN_ALIASES`, causing certain fields to be silently dropped (e.g. Travis tracker's "What's Available?" and "Sources" columns).

## Solution

### Part 1 — Art Tab Image Quality

**Art tab identification** (`fetcher.py`)

The fetcher already discovers all GIDs concurrently. We identify the art tab GID using either signal:
1. The sheet tab name contains "art" (case-insensitive, e.g. "Art", "Album Art", "Artwork")
2. The parsed table's header row contains a column named "image"

**Art tab parsing** (`parser.py`)

New function `parse_art_tab(html: str) -> dict[str, str]`:
- Reuses `detect_columns` + `extract_table` (existing infrastructure)
- Detects `era`, `name`, `image`, `used` columns
- For each row where `used` is truthy (non-empty, not "no"/"false"/"n"), extracts era name + image URL from the `image` cell (first image in cell, falling back to first link)
- Returns `{era_key: image_url}` keyed by the result of `_era_match_key(era_name)`

**Art URL enhancement**

A helper `_enhance_art_url(url: str) -> str`:
- `lh3-6.googleusercontent.com`: strip trailing size suffix (`=sNNN`, `=wNNN`, etc.), append `=s0` (original resolution)
- `lh7-rt.googleusercontent.com`: return as-is (resizing returns 403)
- All other URLs: return as-is
- Applied to art tab image URLs before storing in the map

**Integration into `async_fetch_and_parse` (and sync variant)**

After the best-artist GID is selected, a second pass checks the already-fetched GID HTML results for an art tab:
1. Check each fetched result's tab name / header columns
2. If an art tab is found, call `parse_art_tab`
3. For each era in the parsed artist, look up `_era_match_key(era.name)` in the art map
4. If found and the existing `era.art_url` is absent or lower-quality, overwrite `era.art_url` with the enhanced URL

No extra HTTP requests — art tab HTML was already fetched in the concurrent GID loop.

**Model change**: None — `Era.art_url: str | None` already exists.

### Part 2 — Alternate Header Fields

**`config.py` — COLUMN_ALIASES additions**

| Raw header text | Canonical field |
|---|---|
| `"what's available?"` | `available_length` |
| `"what's available"` | `available_length` |
| `"sources"` | `sources` |

**`models.py` — SongVersion**

Add field:
```python
sources: str | None = Field(None, description="Source attribution, e.g. who originally had the file")
```

**`parser.py` — `_parse_song_row`**

Add:
```python
sources=_get_cell_text(row, col_map.get("sources", -1)) or None,
```

## Files Changed

| File | Change |
|---|---|
| `src/config.py` | Add 3 COLUMN_ALIASES entries |
| `src/models.py` | Add `sources: str | None` to `SongVersion` |
| `src/parser.py` | Add `parse_art_tab()`, `_enhance_art_url()` helper |
| `src/fetcher.py` | Art tab detection + overlay in `async_fetch_and_parse` and `fetch_and_parse` |

No frontend changes needed — `EraCard.vue` already reads `era.art_url` and pipes it through `enhanceGoogleImageUrl` + `/api/image-proxy`.

## Non-Goals

- No new API endpoints
- No changes to caching strategy
- No changes to the `_IMAGE_ALLOWED_DOMAINS` allowlist (art tab images are from the same Google domains)
- No changes to `Song.dict()` — `sources` surfaces naturally via Pydantic serialization
