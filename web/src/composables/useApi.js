/**
 * LeakSheet API client — thin wrapper around fetch().
 */

const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

/** POST /api/parse — parse a tracker URL */
export function parseTracker(url, artistName = null) {
  return request('/parse', {
    method: 'POST',
    body: JSON.stringify({ url, artist_name: artistName }),
  })
}

/** GET /api/artists — list all loaded artists */
export function listArtists() {
  return request('/artists')
}

/** GET /api/artists/:slug — full artist data with eras */
export function getArtist(slug) {
  return request(`/artists/${slug}`)
}

/** GET /api/artists/:slug/eras/:index — single era with songs */
export function getEra(slug, eraIndex) {
  return request(`/artists/${slug}/eras/${eraIndex}`)
}

/** GET /api/search?q=... — full-text search */
export function searchSongs(query) {
  return request(`/search?q=${encodeURIComponent(query)}`)
}
