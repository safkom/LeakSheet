import { reactive, watch } from 'vue'
import { BADGE_MAP, BEST_OF_BADGES } from './useUtils'
import type { SongVersion } from './useEraFiltering'

/**
 * Global audio player — shared across all components.
 * Uses HTML5 Audio with backend stream proxy to avoid CORS.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface QueueItem {
  id: number
  version: SongVersion
  artistName: string
  eraName: string
  artUrl: string
}

interface EraSongContext {
  eraName: string
  artistName: string
  artUrl: string
  versions: SongVersion[]
}

export interface PlayerState {
  track: SongVersion | null
  artistName: string
  eraName: string
  artUrl: string
  isPlaying: boolean
  currentTime: number
  duration: number
  buffered: number
  loading: boolean
  error: string
  streamUrl: string
  volume: number
  queue: QueueItem[]
  bestOfQueue: boolean
  _eraSongs: EraSongContext | null
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** Monotonic ID counter for queue items — survives reactive mutations */
let _queueIdCounter = 0

/** Restore persisted volume (0-1) from localStorage */
function _loadVolume(): number {
  try {
    const v = parseFloat(localStorage.getItem('leaksheet_volume') || '')
    return isFinite(v) ? Math.max(0, Math.min(1, v)) : 1
  } catch { return 1 }
}

export const playerState: PlayerState = reactive({
  /** Currently queued track (SongVersion object) */
  track: null,
  /** Artist name for display */
  artistName: '',
  /** Era name for display */
  eraName: '',
  /** Era cover art URL for display */
  artUrl: '',
  /** Is actively playing */
  isPlaying: false,
  /** Current playback time in seconds */
  currentTime: 0,
  /** Total duration in seconds */
  duration: 0,
  /** Buffered fraction 0-1 */
  buffered: 0,
  /** Loading state */
  loading: false,
  /** Error message */
  error: '',
  /** The resolved stream URL currently playing */
  streamUrl: '',
  /** Volume 0-1 */
  volume: _loadVolume(),
  /** Playback queue */
  queue: [],
  /** Whether the current auto-queue is best-of filtered */
  bestOfQueue: false,
  /** Currently loaded era songs — used for auto-advancing to next song */
  _eraSongs: null,
})

// Persist volume changes to localStorage (debounced to avoid write spam)
let _volTimer: ReturnType<typeof setTimeout> | null = null
watch(() => playerState.volume, (v) => {
  if (_volTimer) clearTimeout(_volTimer)
  _volTimer = setTimeout(() => {
    try { localStorage.setItem('leaksheet_volume', String(v)) } catch {}
  }, 300)
})

// ---------------------------------------------------------------------------
// Audio element (singleton)
// ---------------------------------------------------------------------------

let _audio: HTMLAudioElement | null = null

function _getAudio() {
  if (!_audio) {
    _audio = new Audio()
    _audio.preload = 'auto'

    let _lastPosUpdate = 0
    _audio.addEventListener('timeupdate', () => {
      playerState.currentTime = _audio.currentTime
      // Update MediaSession position state (~1Hz, not every timeupdate)
      const now = performance.now()
      if (now - _lastPosUpdate > 1000 && 'mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
        _lastPosUpdate = now
        try {
          // Fall back to metadata duration when the audio element hasn't
          // determined a finite duration yet (e.g. stream without Content-Length).
          const effectiveDuration = isFinite(_audio.duration) && _audio.duration > 0
            ? _audio.duration
            : playerState.duration
          if (effectiveDuration > 0) {
            navigator.mediaSession.setPositionState({
              duration: effectiveDuration,
              playbackRate: _audio.playbackRate,
              // Clamp position so iOS never sees position > duration (shows "ended").
              position: Math.min(_audio.currentTime, effectiveDuration),
            })
          }
        } catch (e) { /* ignore */ }
      }
    })

    _audio.addEventListener('durationchange', () => {
      if (isFinite(_audio.duration)) {
        playerState.duration = _audio.duration
        // Push the updated duration to iOS Control Center immediately rather than
        // waiting up to 1s for the next timeupdate cycle.
        if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
          try {
            navigator.mediaSession.setPositionState({
              duration: _audio.duration,
              playbackRate: _audio.playbackRate,
              position: Math.min(_audio.currentTime, _audio.duration),
            })
          } catch (e) { /* ignore */ }
        }
      }
    })

    _audio.addEventListener('progress', () => {
      if (_audio.buffered.length > 0) {
        const end = _audio.buffered.end(_audio.buffered.length - 1)
        playerState.buffered = playerState.duration > 0
          ? end / playerState.duration
          : 0
      }
    })

    _audio.addEventListener('playing', () => {
      playerState.isPlaying = true
      playerState.loading = false
      playerState.error = ''
    })

    _audio.addEventListener('pause', () => {
      playerState.isPlaying = false
    })

    _audio.addEventListener('ended', () => {
      playerState.isPlaying = false
      playerState.currentTime = 0
      _playNext()
    })

    _audio.addEventListener('waiting', () => {
      playerState.loading = true
    })

    _audio.addEventListener('canplay', () => {
      playerState.loading = false
    })

    _audio.addEventListener('error', () => {
      const code = _audio.error?.code
      const msgs = {
        1: 'Playback aborted',
        2: 'Network error',
        3: 'Decode error',
        4: 'Source not supported',
      }
      playerState.error = msgs[code] || 'Playback error'
      playerState.isPlaying = false
      playerState.loading = false
    })
  }
  return _audio
}


// ---------------------------------------------------------------------------
// Stream URL helpers
// ---------------------------------------------------------------------------

/**
 * Resolve a file-sharing link to its direct stream URL (client-side).
 *
 * pillows.su / pillowcase.su  → https://api.pillows.su/api/get/{id}  (direct, no proxy needed)
 * imgur.gg / temp.imgur.gg     → proxied through /api/stream (CORS restricted)
 */
const _PILLOWS_RE = /^https?:\/\/(?:www\.)?(pillows\.su|pillowcase\.su)\/f\/([A-Za-z0-9_-]+)/i
const _IMGUR_RE = /^https?:\/\/(?:www\.)?((?:temp\.)?imgur\.gg)\/f\/([A-Za-z0-9_-]+)/i
const _FROSTE_RE = /^https?:\/\/music\.froste\.lol\/song\/([a-f0-9]+)/i
const _KRAKEN_RE = /^https?:\/\/(?:www\.)?krakenfiles\.com\/view\/[A-Za-z0-9_-]+\/file\.html/i

function _resolveStreamUrl(originalLink: string): { url: string; direct: boolean } | null {
  // Pillowcase: proxy through backend — pillows.su returns broken
  // Content-Length in 206 responses which iOS Safari rejects.
  let m = _PILLOWS_RE.exec(originalLink)
  if (m) {
    return { url: `/api/stream?url=${encodeURIComponent(originalLink)}`, direct: false }
  }

  // Imgur: proxy through our backend (CORS restricted)
  m = _IMGUR_RE.exec(originalLink)
  if (m) {
    return { url: `/api/stream?url=${encodeURIComponent(originalLink)}`, direct: false }
  }

  // music.froste.lol: proxy through backend — server returns application/octet-stream
  // for FLAC files; the backend sniffs magic bytes and corrects the MIME type.
  m = _FROSTE_RE.exec(originalLink)
  if (m) {
    return { url: `/api/stream?url=${encodeURIComponent(originalLink)}`, direct: false }
  }

  // krakenfiles.com: proxy through backend (CORS restricted, requires page scraping)
  m = _KRAKEN_RE.exec(originalLink)
  if (m) {
    return { url: `/api/stream?url=${encodeURIComponent(originalLink)}`, direct: false }
  }

  return null
}

/**
 * Find the first streamable link from a version's links array.
 * Returns the original link or null.
 */
const _STREAM_HOSTS = /^https?:\/\/(?:(?:www\.)?(pillows\.su|pillowcase\.su|(?:temp\.)?imgur\.gg)\/f\/|music\.froste\.lol\/song\/[a-f0-9]+|(?:www\.)?krakenfiles\.com\/view\/[A-Za-z0-9_-]+\/file\.html)/i

export function findStreamableLink(links: string[] | null | undefined): string | null {
  if (!links?.length) return null
  for (const link of links) {
    if (_STREAM_HOSTS.test(link)) return link
  }
  return null
}

/**
 * Check if a SongVersion has any streamable links.
 */
export function isStreamable(version: SongVersion | null | undefined): boolean {
  return findStreamableLink(version?.links) !== null
}


// ---------------------------------------------------------------------------
// Playback controls
// ---------------------------------------------------------------------------

/**
 * Register the static MediaSession action handlers that never change between tracks.
 * Called once at module initialization.
 */
function _initStaticMediaSessionHandlers() {
  if (!('mediaSession' in navigator)) return
  navigator.mediaSession.setActionHandler('seekbackward', () => {
    seekTo(Math.max(0, playerState.currentTime - 10))
  })
  navigator.mediaSession.setActionHandler('seekforward', () => {
    seekTo(playerState.currentTime + 10)
  })
  navigator.mediaSession.setActionHandler('previoustrack', () => {
    // If > 3s into the song, restart; otherwise no-op (no history)
    if (playerState.currentTime > 3) {
      seekTo(0)
    }
  })
  navigator.mediaSession.setActionHandler('stop', () => stopTrack())
}

/**
 * Update the browser MediaSession metadata (iOS lock screen, Android notification, etc.)
 * and re-register only the dynamic action handlers that reference the current track state.
 */
function _updateMediaSession() {
  if (!('mediaSession' in navigator)) return

  const track = playerState.track
  if (!track) {
    navigator.mediaSession.metadata = null
    return
  }

  // Build title with badge emoji and version tag
  let title = track.name || ''
  const badge = track.badge
  if (badge && BADGE_MAP[badge]) {
    title = `${BADGE_MAP[badge]} ${title}`
  }
  if (track.version_tag) {
    title += ` [${track.version_tag}]`
  }

  const artwork = []
  if (playerState.artUrl) {
    const fullUrl = playerState.artUrl.startsWith('//') ? 'https:' + playerState.artUrl : playerState.artUrl
    if (fullUrl.startsWith('http')) {
      const proxyUrl = `${window.location.origin}/api/image-proxy?url=${encodeURIComponent(fullUrl)}`
      artwork.push({ src: proxyUrl, sizes: '512x512', type: 'image/jpeg' })
    }
  }

  navigator.mediaSession.metadata = new MediaMetadata({
    title,
    artist: playerState.artistName || '',
    album: playerState.eraName || '',
    artwork,
  })

  // Re-register only the dynamic handlers (vary per track / playback state)
  navigator.mediaSession.setActionHandler('play', () => togglePlay())
  navigator.mediaSession.setActionHandler('pause', () => togglePlay())
  navigator.mediaSession.setActionHandler('seekto', (details) => {
    if (details.seekTime != null) seekTo(details.seekTime)
  })
  navigator.mediaSession.setActionHandler('nexttrack', () => _playNext())
}

// Register static MediaSession handlers once when the module is first loaded.
_initStaticMediaSessionHandlers()

export function playTrack(version: SongVersion | null, artistName = '', eraName = '', artUrl = ''): void {
  const link = findStreamableLink(version?.links)

  playerState.track = version
  playerState.artistName = artistName
  playerState.eraName = eraName
  playerState.artUrl = artUrl
  playerState.currentTime = 0
  playerState.buffered = 0
  playerState.error = ''
  playerState.duration = _parseDuration(version?.track_length)

  if (link) {
    const resolved = _resolveStreamUrl(link)
    if (!resolved) {
      playerState.streamUrl = ''
      playerState.isPlaying = false
      playerState.loading = false
      playerState.error = 'Stream host not supported'
      return
    }

    const audio = _getAudio()
    playerState.streamUrl = resolved.url
    playerState.loading = true

    audio.src = resolved.url
    audio.volume = playerState.volume
    audio.play().catch(() => {
      // Browser may block autoplay — tell user to tap play
      playerState.isPlaying = false
      playerState.loading = false
      playerState.error = 'Tap ▶ to start playback'
    })
  } else {
    // No streamable link — show track info only (no audio)
    playerState.streamUrl = ''
    playerState.isPlaying = false
    playerState.loading = false
  }

  _updateMediaSession()
}

export function togglePlay(): void {
  const audio = _getAudio()

  if (!audio.src && playerState.track) {
    // Try to play current track
    const link = findStreamableLink(playerState.track?.links)
    if (link) {
      const resolved = _resolveStreamUrl(link)
      if (resolved) {
        audio.src = resolved.url
        audio.volume = playerState.volume
        audio.play().catch((e) => {
          playerState.isPlaying = false
          playerState.error = e instanceof Error ? e.message : 'Playback failed'
        })
      }
    }
    return
  }

  if (playerState.isPlaying) {
    audio.pause()
  } else {
    audio.play().catch((e) => {
      playerState.isPlaying = false
      playerState.loading = false
      playerState.error = e instanceof Error ? e.message : 'Playback failed'
    })
  }
}

export function addToQueue(version: SongVersion, artistName = '', eraName = '', artUrl = ''): void {
  playerState.queue.push({ id: ++_queueIdCounter, version, artistName, eraName, artUrl })
}

export function removeFromQueue(index: number): void {
  if (index >= 0 && index < playerState.queue.length) {
    playerState.queue.splice(index, 1)
  }
}

export function clearQueue(): void {
  playerState.queue.splice(0, playerState.queue.length)
}

export function moveInQueue(fromIndex: number, toIndex: number): void {
  if (fromIndex < 0 || fromIndex >= playerState.queue.length) return
  if (toIndex < 0 || toIndex >= playerState.queue.length) return
  const [item] = playerState.queue.splice(fromIndex, 1)
  playerState.queue.splice(toIndex, 0, item)
}

export function playFromQueue(index: number): void {
  if (index < 0 || index >= playerState.queue.length) return
  const item = playerState.queue.splice(index, 1)[0]
  playTrack(item.version, item.artistName, item.eraName, item.artUrl)
}

export function stopTrack(): void {
  if (_audio) {
    _audio.pause()
    _audio.src = ''
  }
  playerState.track = null
  playerState.isPlaying = false
  playerState.currentTime = 0
  playerState.duration = 0
  playerState.buffered = 0
  playerState.loading = false
  playerState.error = ''
  playerState.streamUrl = ''
  playerState.artUrl = ''
  playerState._eraSongs = null
  // Queue is preserved — user can still play queued items
  _updateMediaSession()
}

export function seekTo(seconds) {
  const audio = _getAudio()
  if (audio.src && isFinite(seconds)) {
    audio.currentTime = Math.max(0, Math.min(seconds, audio.duration || Infinity))
  }
}

export function setVolume(v) {
  playerState.volume = Math.max(0, Math.min(1, v))
  if (_audio) {
    _audio.volume = playerState.volume
  }
}


// ---------------------------------------------------------------------------
// Auto-queue: populate queue from era songs
// ---------------------------------------------------------------------------

/**
 * Set the era song list for auto-advance.
 * Called by ArtistView watcher when a track starts playing — the era context
 * is used so the next song plays automatically when the current one finishes.
 * If bestOf is true, only best/special songs are auto-advanced.
 */
export function setEraSongs(versions: SongVersion[], artistName: string, eraName: string, artUrl: string, bestOf = false): void {
  playerState._eraSongs = { eraName, artistName, artUrl, versions }
  playerState.bestOfQueue = bestOf
}

/** Advance to next track: from queue first, then auto-advance era */
function _playNext() {
  if (playerState.queue.length > 0) {
    const next = playerState.queue.shift()
    playTrack(next.version, next.artistName, next.eraName, next.artUrl)
    return
  }
  // Queue empty — auto-advance to next era song directly (don't fill queue)
  _playNextEraSong()
}

/** Find and play the next song in the era without populating the queue */
function _playNextEraSong() {
  const era = playerState._eraSongs
  if (!era || !playerState.track) return

  const currentIdx = era.versions.findIndex(v => isTrackMatch(v))
  if (currentIdx === -1) return

  const remaining = era.versions.slice(currentIdx + 1)
  for (const version of remaining) {
    if (!findStreamableLink(version.links)) continue
    if (playerState.bestOfQueue && !BEST_OF_BADGES.has(version.badge ?? '')) continue
    playTrack(version, era.artistName, era.eraName, era.artUrl)
    return
  }
  // No more songs in era
}

/** Skip to next track (exposed for UI) */
export function playNext() {
  _playNext()
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Check if a version matches the currently playing track.
 * Uses value comparison (not reference equality) so it works after re-parsing.
 * Compares name + version_tag + first link for robust identity.
 */
export function isTrackMatch(version: SongVersion | null | undefined): boolean {
  if (!version || !playerState.track) return false
  return version.name === playerState.track.name
    && version.version_tag === playerState.track.version_tag
    && (version.links?.[0] || '') === (playerState.track.links?.[0] || '')
}

/** Parse "3:14" → 194 seconds */
function _parseDuration(str: string | null | undefined): number {
  if (!str || str.includes('?')) return 0
  const parts = str.split(':').map(Number)
  if (parts.some(isNaN)) return 0
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  return 0
}

/** Format seconds → "3:14" */
export function formatTime(seconds: number): string {
  if (!seconds || seconds <= 0 || !isFinite(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/**
 * Request original full-size Google image (=s0 means "no resize").
 * Google CDN URLs from sheets come with small default size suffixes.
 *
 * Supported domains:
 *  - lh3-lh6.googleusercontent.com  → =s0 works
 *  - docs.google.com/sheets-images-rt → =s0 works (=sNNN with N>0 → 302 login)
 *  - lh7-rt.googleusercontent.com    → cannot be resized (?key= → 403)
 */
export function enhanceGoogleImageUrl(url: string): string {
  if (!url) return url
  // lh7-rt with ?key= — cannot be resized (returns 403)
  if (/lh7-rt\.googleusercontent\.com/.test(url)) return url
  // lh3-6 googleusercontent + docs.google.com/sheets-images — =s0 for original
  if (/lh[3-6]\.googleusercontent\.com|docs\.google\.com\/sheets-images/.test(url)) {
    return url.replace(/=[swh]\d+(-[swh]\d+)*$/, '') + '=s0'
  }
  return url
}

/**
 * Build proxy URL for an art image.
 * Handles protocol-relative URLs and routes through /api/image-proxy.
 */
export function artProxyUrl(rawUrl: string | null | undefined): string | null {
  if (!rawUrl) return null
  const fullUrl = rawUrl.startsWith('//') ? 'https:' + rawUrl : rawUrl
  if (fullUrl.startsWith('http')) {
    return `/api/image-proxy?url=${encodeURIComponent(fullUrl)}`
  }
  return rawUrl
}
