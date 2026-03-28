/**
 * Favourites composable — persist favourited songs in localStorage.
 *
 * Uses module-level singleton state (same pattern as usePlayer, useEraColors)
 * so all components share a single reactive list without a provider.
 *
 * Composite key format: `${artistSlug}::${eraName}::${baseName}`
 * The data model has no server-assigned IDs, so this triple is the stable
 * identifier for a song across re-parses of the same tracker.
 */

import { shallowRef, triggerRef } from 'vue'
import type { Song } from './useEraFiltering'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FavouriteEntry {
  key: string
  artistSlug: string
  artistName: string
  sourceUrl: string | null
  eraName: string
  eraArt: string | null
  song: Song
  addedAt: number
}

// ---------------------------------------------------------------------------
// Module-level singleton state
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'leaksheet_favourites'

function _load(): FavouriteEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const _list = shallowRef<FavouriteEntry[]>(_load())

// Debounced persistence so rapid toggle bursts don't thrash localStorage
let _saveTimer: ReturnType<typeof setTimeout> | null = null
function _scheduleSave() {
  if (_saveTimer) clearTimeout(_saveTimer)
  _saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(_list.value))
    } catch {
      // quota exceeded — silently ignore
    }
  }, 500)
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Reactive list of all favourited entries, sorted newest-first. */
export const favourites = _list

/** Build the composite key for a song. */
export function favouriteKey(artistSlug: string, eraName: string, baseName: string): string {
  return `${artistSlug}::${eraName}::${baseName}`
}

/** Returns true if the song is currently favourited. */
export function isFavourited(artistSlug: string, eraName: string, baseName: string): boolean {
  const key = favouriteKey(artistSlug, eraName, baseName)
  return _list.value.some(e => e.key === key)
}

/**
 * Add or remove a song from favourites.
 * Returns true if the song was added, false if it was removed.
 */
export function toggleFavourite(
  song: Song,
  artistSlug: string,
  artistName: string,
  sourceUrl: string | null,
  eraName: string,
  eraArt: string | null,
): boolean {
  const key = favouriteKey(artistSlug, eraName, song.base_name)
  const existing = _list.value.findIndex(e => e.key === key)

  if (existing !== -1) {
    // Remove
    _list.value = _list.value.filter((_, i) => i !== existing)
    triggerRef(_list)
    _scheduleSave()
    return false
  } else {
    // Add (prepend so newest appears first)
    const entry: FavouriteEntry = {
      key,
      artistSlug,
      artistName,
      sourceUrl,
      eraName,
      eraArt,
      song,
      addedAt: Date.now(),
    }
    _list.value = [entry, ..._list.value]
    triggerRef(_list)
    _scheduleSave()
    return true
  }
}

/** Remove a favourite by its composite key. */
export function removeFavourite(key: string): void {
  _list.value = _list.value.filter(e => e.key !== key)
  triggerRef(_list)
  _scheduleSave()
}

/** Remove all favourites. */
export function clearFavourites(): void {
  _list.value = []
  triggerRef(_list)
  _scheduleSave()
}

/**
 * Return all favourites for a specific artist, sorted by era then addedAt.
 * Used in ArtistView's per-tracker favourites filter.
 */
export function favouritesForArtist(artistSlug: string): FavouriteEntry[] {
  return _list.value.filter(e => e.artistSlug === artistSlug)
}

/**
 * Return favourites grouped by artistName > eraName.
 * Used in the global FavouritesPanel.
 */
export function favouritesByArtist(): { artistName: string; artistSlug: string; sourceUrl: string | null; eras: { eraName: string; eraArt: string | null; entries: FavouriteEntry[] }[] }[] {
  const artistMap = new Map<string, { artistName: string; artistSlug: string; sourceUrl: string | null; eras: Map<string, { eraName: string; eraArt: string | null; entries: FavouriteEntry[] }> }>()

  for (const entry of _list.value) {
    if (!artistMap.has(entry.artistSlug)) {
      artistMap.set(entry.artistSlug, {
        artistName: entry.artistName,
        artistSlug: entry.artistSlug,
        sourceUrl: entry.sourceUrl,
        eras: new Map(),
      })
    }
    const artistGroup = artistMap.get(entry.artistSlug)!
    if (!artistGroup.eras.has(entry.eraName)) {
      artistGroup.eras.set(entry.eraName, { eraName: entry.eraName, eraArt: entry.eraArt, entries: [] })
    }
    artistGroup.eras.get(entry.eraName)!.entries.push(entry)
  }

  return [...artistMap.values()].map(a => ({
    artistName: a.artistName,
    artistSlug: a.artistSlug,
    sourceUrl: a.sourceUrl,
    eras: [...a.eras.values()],
  }))
}
