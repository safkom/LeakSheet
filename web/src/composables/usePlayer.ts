import { reactive, watch } from 'vue'

/**
 * Global audio player — shared across all components.
 * Uses HTML5 Audio with backend stream proxy to avoid CORS.
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export const playerState = reactive({
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
  volume: 1,
  /** Playback queue (array of { version, artistName, eraName, artUrl }) */
  queue: [],
})

// ---------------------------------------------------------------------------
// Audio element (singleton)
// ---------------------------------------------------------------------------

let _audio = null

function _getAudio() {
  if (!_audio) {
    _audio = new Audio()
    _audio.preload = 'auto'

    _audio.addEventListener('timeupdate', () => {
      playerState.currentTime = _audio.currentTime
      // Update MediaSession position state
      if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
        try {
          if (isFinite(_audio.duration) && _audio.duration > 0) {
            navigator.mediaSession.setPositionState({
              duration: _audio.duration,
              playbackRate: _audio.playbackRate,
              position: _audio.currentTime,
            })
          }
        } catch (e) { /* ignore */ }
      }
    })

    _audio.addEventListener('durationchange', () => {
      if (isFinite(_audio.duration)) {
        playerState.duration = _audio.duration
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
      // Auto-advance queue
      if (playerState.queue.length > 0) {
        const next = playerState.queue.shift()
        playTrack(next.version, next.artistName, next.eraName, next.artUrl)
      }
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

function _resolveStreamUrl(originalLink) {
  // Pillowcase: use their API directly (supports CORS)
  let m = _PILLOWS_RE.exec(originalLink)
  if (m) {
    return { url: `https://api.pillows.su/api/get/${m[2]}`, direct: true }
  }

  // Imgur: proxy through our backend (CORS restricted)
  m = _IMGUR_RE.exec(originalLink)
  if (m) {
    return { url: `/api/stream?url=${encodeURIComponent(originalLink)}`, direct: false }
  }

  // music.froste.lol: direct (supports CORS + Range natively)
  m = _FROSTE_RE.exec(originalLink)
  if (m) {
    return { url: `https://music.froste.lol/song/${m[1]}/file`, direct: true }
  }

  return null
}

/**
 * Find the first streamable link from a version's links array.
 * Returns the original link or null.
 */
const _STREAM_HOSTS = /^https?:\/\/(?:(?:www\.)?(pillows\.su|pillowcase\.su|(?:temp\.)?imgur\.gg)\/f\/|music\.froste\.lol\/song\/[a-f0-9]+)/i

export function findStreamableLink(links) {
  if (!links?.length) return null
  for (const link of links) {
    if (_STREAM_HOSTS.test(link)) return link
  }
  return null
}

/**
 * Check if a SongVersion has any streamable links.
 */
export function isStreamable(version) {
  return findStreamableLink(version?.links) !== null
}


// ---------------------------------------------------------------------------
// Playback controls
// ---------------------------------------------------------------------------

/** Badge emoji map for MediaSession titles */
const _BADGE_EMOJI = {
  best: '⭐',
  special: '✨',
  grail: '🏆',
  wanted: '🏅',
  worst: '🗑️',
  ai: '🤖',
}

/**
 * Update the browser MediaSession metadata (iOS lock screen, Android notification, etc.)
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
  if (badge && _BADGE_EMOJI[badge]) {
    title = `${_BADGE_EMOJI[badge]} ${title}`
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

  // Set action handlers
  navigator.mediaSession.setActionHandler('play', () => togglePlay())
  navigator.mediaSession.setActionHandler('pause', () => togglePlay())
  navigator.mediaSession.setActionHandler('seekbackward', () => {
    seekTo(Math.max(0, playerState.currentTime - 10))
  })
  navigator.mediaSession.setActionHandler('seekforward', () => {
    seekTo(playerState.currentTime + 10)
  })
  navigator.mediaSession.setActionHandler('seekto', (details) => {
    if (details.seekTime != null) seekTo(details.seekTime)
  })
  navigator.mediaSession.setActionHandler('stop', () => stopTrack())
}

export function playTrack(version, artistName = '', eraName = '', artUrl = '') {
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
      return
    }

    const audio = _getAudio()
    playerState.streamUrl = resolved.url
    playerState.loading = true

    audio.src = resolved.url
    audio.volume = playerState.volume
    audio.play().catch(() => {
      // Browser may block autoplay — user sees play button
      playerState.isPlaying = false
      playerState.loading = false
    })
  } else {
    // No streamable link — show track info only (no audio)
    playerState.streamUrl = ''
    playerState.isPlaying = false
    playerState.loading = false
  }

  _updateMediaSession()
}

export function togglePlay() {
  const audio = _getAudio()

  if (!audio.src && playerState.track) {
    // Try to play current track
    const link = findStreamableLink(playerState.track?.links)
    if (link) {
      const resolved = _resolveStreamUrl(link)
      if (resolved) {
        audio.src = resolved.url
        audio.volume = playerState.volume
        audio.play().catch(() => {})
      }
    }
    return
  }

  if (playerState.isPlaying) {
    audio.pause()
  } else {
    audio.play().catch(() => {})
  }
}

export function addToQueue(version, artistName = '', eraName = '', artUrl = '') {
  playerState.queue.push({ version, artistName, eraName, artUrl })
}

export function removeFromQueue(index) {
  if (index >= 0 && index < playerState.queue.length) {
    playerState.queue.splice(index, 1)
  }
}

export function clearQueue() {
  playerState.queue.splice(0, playerState.queue.length)
}

export function moveInQueue(fromIndex, toIndex) {
  if (fromIndex < 0 || fromIndex >= playerState.queue.length) return
  if (toIndex < 0 || toIndex >= playerState.queue.length) return
  const [item] = playerState.queue.splice(fromIndex, 1)
  playerState.queue.splice(toIndex, 0, item)
}

export function playFromQueue(index) {
  if (index < 0 || index >= playerState.queue.length) return
  const item = playerState.queue.splice(index, 1)[0]
  playTrack(item.version, item.artistName, item.eraName, item.artUrl)
}

export function stopTrack() {
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
  playerState.queue = []
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
// Helpers
// ---------------------------------------------------------------------------

/**
 * Check if a version matches the currently playing track.
 * Uses value comparison (not reference equality) so it works after re-parsing.
 * Compares name + version_tag + first link for robust identity.
 */
export function isTrackMatch(version) {
  if (!version || !playerState.track) return false
  return version.name === playerState.track.name
    && version.version_tag === playerState.track.version_tag
    && (version.links?.[0] || '') === (playerState.track.links?.[0] || '')
}

/** Parse "3:14" → 194 seconds */
function _parseDuration(str) {
  if (!str || str.includes('?')) return 0
  const parts = str.split(':').map(Number)
  if (parts.some(isNaN)) return 0
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  return 0
}

/** Format seconds → "3:14" */
export function formatTime(seconds) {
  if (!seconds || seconds <= 0 || !isFinite(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/**
 * Build proxy URL for an art image.
 * Handles protocol-relative URLs and routes through /api/image-proxy.
 */
export function artProxyUrl(rawUrl) {
  if (!rawUrl) return null
  const fullUrl = rawUrl.startsWith('//') ? 'https:' + rawUrl : rawUrl
  if (fullUrl.startsWith('http')) {
    return `/api/image-proxy?url=${encodeURIComponent(fullUrl)}`
  }
  return rawUrl
}
