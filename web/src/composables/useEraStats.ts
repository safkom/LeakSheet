/**
 * Era and artist statistics composable.
 *
 * Computes per-era and artist-level stats from the eras array.
 * Reused by ArtistStatsBar, EraCard, and RecentTrackerCard.
 */
import { findStreamableLink } from './usePlayer'
import { eraSongs } from './useEraFiltering'
import type { Era, SongVersion } from './useEraFiltering'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EraStats {
  total: number        // total version count
  available: number    // versions with a streamable link
  snippets: number     // versions where available_length contains "snippet"
  confirmed: number    // versions confirmed to exist but no file
  fullHQ: number       // versions that are full + HQ quality
  percent: number      // available / total * 100, rounded
}

export interface ArtistStats {
  total: number
  available: number
  snippets: number
  confirmed: number
  fullHQ: number
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _isSnippet(v: SongVersion): boolean {
  return (v.available_length ?? '').toLowerCase().includes('snippet')
}

function _isConfirmedOnly(v: SongVersion): boolean {
  // No links and badge is "confirmed" or similar
  if (v.links?.length) return false
  const badge = (v.badge ?? '').toLowerCase()
  return badge.includes('confirmed') || badge === ''
}

function _isFullHQ(v: SongVersion): boolean {
  const al = (v.available_length ?? '').toLowerCase()
  const q = (v.quality ?? '').toLowerCase()
  return (al.includes('full') || al.includes('near full')) && q.includes('hq')
}

// ---------------------------------------------------------------------------
// Pure functions (no reactivity — called from computed refs in components)
// ---------------------------------------------------------------------------

export function eraStats(era: Era): EraStats {
  const songs = eraSongs(era)
  let total = 0
  let available = 0
  let snippets = 0
  let confirmed = 0
  let fullHQ = 0

  for (const song of songs) {
    for (const v of (song.versions || [])) {
      total++
      if (findStreamableLink(v.links)) available++
      if (_isSnippet(v)) snippets++
      if (_isConfirmedOnly(v)) confirmed++
      if (_isFullHQ(v)) fullHQ++
    }
  }

  const percent = total > 0 ? Math.round((available / total) * 100) : 0
  return { total, available, snippets, confirmed, fullHQ, percent }
}

export function artistStats(eras: Era[]): ArtistStats {
  let total = 0
  let available = 0
  let snippets = 0
  let confirmed = 0
  let fullHQ = 0

  for (const era of eras) {
    const s = eraStats(era)
    total += s.total
    available += s.available
    snippets += s.snippets
    confirmed += s.confirmed
    fullHQ += s.fullHQ
  }

  return { total, available, snippets, confirmed, fullHQ }
}
