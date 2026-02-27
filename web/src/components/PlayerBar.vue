<script setup>
import { computed, ref, watch } from 'vue'
import ContextMenu from './ContextMenu.vue'
import SongDescriptionModal from './SongDescriptionModal.vue'
import { playerState, togglePlay, stopTrack, seekTo, setVolume, formatTime, artProxyUrl } from '../composables/usePlayer.js'

const track = computed(() => playerState.track)
const playing = computed(() => playerState.isPlaying)
const loading = computed(() => playerState.loading)
const error = computed(() => playerState.error)
const hasStream = computed(() => !!playerState.streamUrl)

const playerArtSrc = computed(() => artProxyUrl(playerState.artUrl))
const artError = ref(false)

// Reset error state when art URL changes
watch(() => playerState.artUrl, () => { artError.value = false })

const displayName = computed(() => {
  if (!track.value) return ''
  const parts = [track.value.name]
  if (track.value.version_tag) parts.push(`[${track.value.version_tag}]`)
  return parts.join(' ')
})

const displaySub = computed(() => {
  return playerState.eraName || ''
})

const currentTimeStr = computed(() => formatTime(playerState.currentTime))
const durationStr = computed(() => {
  if (playerState.duration > 0 && isFinite(playerState.duration)) return formatTime(playerState.duration)
  return track.value?.track_length || '--:--'
})

const progressPct = computed(() => {
  if (!playerState.duration || !isFinite(playerState.currentTime) || !isFinite(playerState.duration)) return 0
  return (playerState.currentTime / playerState.duration) * 100
})

const bufferedPct = computed(() => {
  const b = playerState.buffered
  return isFinite(b) ? b * 100 : 0
})

// Volume
const volumePct = computed(() => Math.round(playerState.volume * 100))

// Seek on progress bar click
const progressBar = ref(null)

function handleSeek(e) {
  if (!playerState.duration || !isFinite(playerState.duration) || !hasStream.value) return
  if (!progressBar.value) return
  const rect = progressBar.value.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  seekTo(ratio * playerState.duration)
}

function handleVolume(e) {
  if (!e.currentTarget) return
  const rect = e.currentTarget.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  setVolume(ratio)
}

// Player context menu
const playerMenu = ref(null)
const showDescModal = ref(false)
const menuBtnRef = ref(null)

function togglePlayerMenu(e) {
  if (playerMenu.value) {
    playerMenu.value = null
    return
  }
  const btn = menuBtnRef.value
  if (!btn) return
  const rect = btn.getBoundingClientRect()
  playerMenu.value = { x: rect.left, y: rect.top - 4 }
}

function closePlayerMenu() {
  playerMenu.value = null
}

function openTrackDescription() {
  showDescModal.value = true
  playerMenu.value = null
}
</script>

<template>
  <div class="player-bar">
    <!-- Progress bar - top edge of player -->
    <div
      class="progress-bar"
      ref="progressBar"
      @click="handleSeek"
      :class="{ disabled: !hasStream }"
    >
      <div class="progress-buffered" :style="{ width: bufferedPct + '%' }"></div>
      <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
      <div
        v-if="progressPct > 0"
        class="progress-thumb"
        :style="{ left: progressPct + '%' }"
      ></div>
    </div>

    <div class="player-inner">
      <!-- Album art -->
      <div class="player-art" v-if="track">
        <img
          v-if="playerArtSrc && !artError"
          :src="playerArtSrc"
          alt=""
          class="player-art-img"
          @error="artError = true"
        />
        <div v-else class="player-art-placeholder">
          <svg viewBox="0 0 24 24" width="22" height="22">
            <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
          </svg>
        </div>
      </div>

      <!-- Track info -->
      <div class="player-track-info">
        <div class="player-track-name">
          <span v-if="loading" class="loading-dot"></span>
          {{ displayName }}
        </div>
        <div class="player-track-sub">
          <template v-if="error">
            <span class="player-error">{{ error }}</span>
          </template>
          <template v-else>{{ displaySub }}</template>
        </div>
      </div>

      <!-- Controls -->
      <div class="player-controls">
        <button
          class="ctrl-btn"
          :class="{ disabled: !hasStream }"
          @click="togglePlay"
          :title="playing ? 'Pause' : 'Play'"
        >
          <!-- Loading spinner -->
          <svg v-if="loading" class="spinner" viewBox="0 0 24 24" width="28" height="28">
            <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2.5" stroke-dasharray="31.4" stroke-dashoffset="10" stroke-linecap="round"/>
          </svg>
          <!-- Play -->
          <svg v-else-if="!playing" viewBox="0 0 24 24" width="28" height="28">
            <path fill="currentColor" d="M8 5v14l11-7z"/>
          </svg>
          <!-- Pause -->
          <svg v-else viewBox="0 0 24 24" width="28" height="28">
            <path fill="currentColor" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
          </svg>
        </button>
      </div>

      <!-- Right side: time + volume + menu + close -->
      <div class="player-right">
        <span class="player-time" v-if="hasStream">
          {{ currentTimeStr }} / {{ durationStr }}
        </span>
        <span class="player-time" v-else>
          {{ durationStr }}
        </span>

        <!-- Volume -->
        <div class="volume-wrap" v-if="hasStream">
          <svg viewBox="0 0 16 16" width="14" height="14" class="volume-icon">
            <path fill="currentColor" d="M7.56 2.45A.5.5 0 0 1 8 2.9v10.2a.5.5 0 0 1-.82.38L4.25 10.5H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h2.25l2.93-3.03a.5.5 0 0 1 .38-.12z"/>
            <path v-if="playerState.volume > 0" fill="currentColor" d="M10.3 5.7a.5.5 0 0 1 .7 0 4 4 0 0 1 0 4.6.5.5 0 1 1-.7-.7 3 3 0 0 0 0-3.2.5.5 0 0 1 0-.7z" opacity="0.7"/>
          </svg>
          <div class="volume-bar" @click="handleVolume">
            <div class="volume-fill" :style="{ width: volumePct + '%' }"></div>
          </div>
        </div>

        <!-- More options menu -->
        <button
          ref="menuBtnRef"
          class="menu-btn"
          @click.stop="togglePlayerMenu"
          title="More options"
          v-if="track"
        >
          <svg viewBox="0 0 16 16" width="14" height="14">
            <circle cx="8" cy="2" r="1.5" fill="currentColor"/>
            <circle cx="8" cy="8" r="1.5" fill="currentColor"/>
            <circle cx="8" cy="14" r="1.5" fill="currentColor"/>
          </svg>
        </button>

        <button class="close-btn" @click="stopTrack" title="Close player">
          <svg viewBox="0 0 16 16" width="14" height="14">
            <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
          </svg>
        </button>
      </div>
    </div>
  </div>

  <!-- Player context menu -->
  <ContextMenu
    v-if="playerMenu && track"
    :x="playerMenu.x"
    :y="playerMenu.y"
    :version="track"
    :artist-name="playerState.artistName"
    :era-name="playerState.eraName"
    :era-art="playerState.artUrl"
    @close="closePlayerMenu"
    @show-description="openTrackDescription"
  />

  <!-- Track description from player -->
  <SongDescriptionModal
    v-if="showDescModal && track"
    :version="track"
    :era-art="playerState.artUrl"
    :era-name="playerState.eraName"
    :artist-name="playerState.artistName"
    @close="showDescModal = false"
  />
</template>

<style scoped>
.player-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--bg-player);
  border-top: 1px solid var(--border);
  z-index: 200;
  backdrop-filter: blur(12px);
  display: flex;
  flex-direction: column;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

.progress-bar {
  position: relative;
  width: 100%;
  height: 4px;
  background: rgba(255,255,255,0.06);
  cursor: pointer;
  flex-shrink: 0;
  transition: height 0.15s;
}

.progress-bar:hover {
  height: 6px;
}

.progress-bar.disabled {
  cursor: default;
  opacity: 0.3;
}

.progress-buffered {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: rgba(255,255,255,0.08);
  transition: width 0.3s;
}

.progress-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--accent);
  transition: width 0.1s linear;
}

.progress-thumb {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0;
  transition: opacity 0.15s;
}

.progress-bar:hover .progress-thumb {
  opacity: 1;
}

.player-inner {
  height: calc(var(--player-height) - 4px);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
}

/* Album art */
.player-art {
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.player-art-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.player-art-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  opacity: 0.4;
}

.player-track-info {
  flex: 1;
  min-width: 0;
}

.player-track-name {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
  gap: 6px;
}

.player-track-sub {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.player-error {
  color: #f85149;
}

.player-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ctrl-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg-primary);
  transition: background 0.15s;
}

.ctrl-btn:hover {
  background: var(--accent-hover);
}

.ctrl-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-dot::after {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.player-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.player-time {
  color: var(--text-dim);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* Volume */
.volume-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
}

.volume-icon {
  color: var(--text-dim);
  flex-shrink: 0;
}

.volume-bar {
  width: 60px;
  height: 4px;
  background: rgba(255,255,255,0.1);
  border-radius: 2px;
  cursor: pointer;
  position: relative;
}

.volume-fill {
  height: 100%;
  background: var(--text-secondary);
  border-radius: 2px;
  transition: width 0.05s;
}

.menu-btn {
  color: var(--text-dim);
  padding: 6px;
  border-radius: 4px;
  transition: all 0.1s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.menu-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.08);
}

.close-btn {
  color: var(--text-dim);
  padding: 4px;
  border-radius: 4px;
  transition: color 0.1s;
}

.close-btn:hover {
  color: var(--text-primary);
}

@media (max-width: 640px) {
  .player-inner { padding: 0 10px; gap: 8px; }
  .player-track-name { font-size: 12px; }
  .ctrl-btn { width: 36px; height: 36px; }
  .player-right { gap: 8px; }
  .player-time { display: none; }
  .volume-wrap { display: none; }
  .player-art { width: 44px; height: 44px; border-radius: 4px; }
}
</style>
