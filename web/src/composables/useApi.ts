/**
 * LeakSheet API client.
 *
 * POST /api/sheet  { url, artist_name?, use_cache?, force_refresh? } → full Artist JSON
 * GET  /api/image-proxy?url=... → proxied images (CORS bypass)
 * GET  /api/stream?url=... → proxied audio (CORS bypass)
 * POST /api/cache/clear → clear fetch cache
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

// Module-level abort controller for parseSheet — cancels previous request
// when a new one starts.
let _parseAbort: AbortController | null = null

/**
 * POST /api/sheet — parse a tracker URL and return full Artist data.
 * Automatically cancels any in-flight previous request.
 */
export function parseSheet(url, { artistName = null, useCache = true, forceRefresh = false } = {}) {
  // Abort any in-flight request
  if (_parseAbort) {
    _parseAbort.abort()
  }
  _parseAbort = new AbortController()

  return request('/sheet', {
    method: 'POST',
    body: JSON.stringify({
      url,
      artist_name: artistName,
      use_cache: useCache,
      force_refresh: forceRefresh,
    }),
    signal: _parseAbort.signal,
  })
}
