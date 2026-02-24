import { reactive } from 'vue'

/**
 * Global player state — shared across components.
 * The actual playback API will be wired in later;
 * this provides the UI shell state.
 */
export const playerState = reactive({
  /** Currently queued track (SongVersion object) */
  track: null,
  /** Artist name for display */
  artistName: '',
  /** Era name for display */
  eraName: '',
  /** Is actively playing */
  isPlaying: false,
  /** Current time in seconds */
  currentTime: 0,
  /** Total duration in seconds */
  duration: 0,
})

export function playTrack(version, artistName = '', eraName = '') {
  playerState.track = version
  playerState.artistName = artistName
  playerState.eraName = eraName
  playerState.isPlaying = true
  playerState.currentTime = 0
  playerState.duration = _parseDuration(version.track_length)
}

export function togglePlay() {
  playerState.isPlaying = !playerState.isPlaying
}

export function stopTrack() {
  playerState.track = null
  playerState.isPlaying = false
  playerState.currentTime = 0
}

/** Parse "3:14" → 194 seconds */
function _parseDuration(str) {
  if (!str || str.includes('?')) return 0
  const parts = str.split(':').map(Number)
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  return 0
}
