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
 * Build the proxy stream URL for a given original link.
 * Routes through /api/stream?url=<encoded original link>
 */
function _proxyUrl(originalLink) {
  return `/api/stream?url=${encodeURIComponent(originalLink)}`
}

/**
 * Find the first streamable link from a version's links array.
 * Returns the original link or null.
 */
const _STREAM_HOSTS = /^https?:\/\/(?:www\.)?(pillows\.su|pillowcase\.su|(?:temp\.)?imgur\.gg)\/f\//i

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

export function playTrack(version, artistName = '', eraName = '') {
  const link = findStreamableLink(version?.links)

  playerState.track = version
  playerState.artistName = artistName
  playerState.eraName = eraName
  playerState.currentTime = 0
  playerState.buffered = 0
  playerState.error = ''
  playerState.duration = _parseDuration(version?.track_length)

  if (link) {
    const audio = _getAudio()
    const url = _proxyUrl(link)
    playerState.streamUrl = url
    playerState.loading = true

    audio.src = url
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
}

export function togglePlay() {
  const audio = _getAudio()

  if (!audio.src && playerState.track) {
    // Try to play current track
    const link = findStreamableLink(playerState.track?.links)
    if (link) {
      audio.src = _proxyUrl(link)
      audio.volume = playerState.volume
      audio.play().catch(() => {})
    }
    return
  }

  if (playerState.isPlaying) {
    audio.pause()
  } else {
    audio.play().catch(() => {})
  }
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

/** Parse "3:14" → 194 seconds */
function _parseDuration(str) {
  if (!str || str.includes('?')) return 0
  const parts = str.split(':').map(Number)
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
