/**
 * LeakSheet API client.
 *
 * POST /api/sheet  { url, artist_name?, use_cache?, force_refresh? } → full Artist JSON
 * GET  /api/image-proxy?url=... → proxied images (CORS bypass)
 * GET  /api/stream?url=... → proxied audio (CORS bypass)
 * POST /api/cache/clear → clear fetch cache
 */

import type { Artist } from './useEraFiltering'

const BASE = '/api'

function _buildSignal(callerSignal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(90000)
  if (!callerSignal) return timeout
  return AbortSignal.any([callerSignal, timeout])
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers as Record<string, string>) },
    ...options,
    signal: _buildSignal(options.signal as AbortSignal | undefined),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

// Module-level abort controller for parseSheet — cancels previous request
// when a new one starts.
let _parseAbort: AbortController | null = null

// Sentinel abort reason for user-initiated cancellations.
// Using object identity lets the catch block distinguish "user submitted a new
// URL" (silent) from any kind of timeout or network error (should show message).
export const USER_ABORT = new DOMException('user cancelled', 'AbortError')

export interface ParseSheetOptions {
  artistName?: string | null
  useCache?: boolean
  forceRefresh?: boolean
}

/**
 * POST /api/sheet — parse a tracker URL and return full Artist data.
 * Automatically cancels any in-flight previous request.
 */
export function parseSheet(url: string, { artistName = null, useCache = true, forceRefresh = false }: ParseSheetOptions = {}): Promise<Artist> {
  // Abort any in-flight request with our sentinel so the catch block can
  // tell this apart from a timeout or other error.
  if (_parseAbort) {
    _parseAbort.abort(USER_ABORT)
  }
  _parseAbort = new AbortController()

  return request<Artist>('/sheet', {
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
