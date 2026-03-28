/**
 * Recent trackers composable.
 *
 * Extracted from App.vue. Manages the localStorage-persisted list of
 * recently viewed trackers with extended metadata for rich card display.
 */
import { ref } from 'vue'
import { artistStats } from './useEraStats'
import type { Artist } from './useEraFiltering'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RecentTracker {
  name: string
  slug: string
  source_url: string
  total_songs: number
  artUrl: string | null
  stats: {
    available: number
    snippets: number
    confirmed: number
  }
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'leaksheet_recent_trackers'

function _load(): RecentTracker[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function _save(entries: RecentTracker[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch { /* quota exceeded — ignore */ }
}

// ---------------------------------------------------------------------------
// Module-level state (singleton across all component instances)
// ---------------------------------------------------------------------------

export const recentTrackers = ref<RecentTracker[]>(_load())

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

/** Save or update a tracker in history after a successful load. */
export function saveRecentTracker(artist: Artist): void {
  const artUrl = artist.eras?.find(e => e.art_url)?.art_url ?? null
  const stats = artistStats(artist.eras ?? [])

  const entry: RecentTracker = {
    name: artist.name,
    slug: artist.slug,
    source_url: artist.source_url ?? '',
    total_songs: artist.total_songs ?? 0,
    artUrl,
    stats: {
      available: stats.available,
      snippets: stats.snippets,
      confirmed: stats.confirmed,
    },
  }

  const existing = recentTrackers.value.findIndex(h => h.source_url === entry.source_url)
  if (existing !== -1) {
    recentTrackers.value.splice(existing, 1)
  }
  recentTrackers.value.unshift(entry)

  // Cap at 20
  if (recentTrackers.value.length > 20) {
    recentTrackers.value = recentTrackers.value.slice(0, 20)
  }

  _save(recentTrackers.value)
}

export function clearRecentTrackers(): void {
  recentTrackers.value = []
  localStorage.removeItem(STORAGE_KEY)
}

export function removeRecentTracker(sourceUrl: string): void {
  recentTrackers.value = recentTrackers.value.filter(h => h.source_url !== sourceUrl)
  _save(recentTrackers.value)
}
