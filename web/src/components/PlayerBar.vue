<script setup>
import { computed } from 'vue'
import { playerState, togglePlay, stopTrack } from '../composables/usePlayer.js'

const track = computed(() => playerState.track)
const isPlaying = computed(() => playerState.isPlaying)

const displayName = computed(() => {
  if (!track.value) return ''
  return track.value.name
})

const displaySub = computed(() => {
  const parts = []
  if (playerState.artistName) parts.push(playerState.artistName)
  if (playerState.eraName) parts.push(playerState.eraName)
  return parts.join(' · ')
})

const displayLength = computed(() => track.value?.track_length || '--:--')

function formatTime(seconds) {
  if (!seconds || seconds <= 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="player-bar">
    <div class="player-track-info">
      <div class="player-track-name">{{ displayName }}</div>
      <div class="player-track-sub">{{ displaySub }}</div>
    </div>

    <div class="player-controls">
      <button class="ctrl-btn" @click="togglePlay">
        <!-- Play -->
        <svg v-if="!isPlaying" viewBox="0 0 24 24" width="28" height="28">
          <path fill="currentColor" d="M8 5v14l11-7z"/>
        </svg>
        <!-- Pause -->
        <svg v-else viewBox="0 0 24 24" width="28" height="28">
          <path fill="currentColor" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
        </svg>
      </button>
    </div>

    <div class="player-right">
      <span class="player-time">{{ displayLength }}</span>
      <button class="close-btn" @click="stopTrack" title="Close player">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.player-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: var(--player-height);
  background: var(--bg-player);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 16px;
  z-index: 200;
  backdrop-filter: blur(12px);
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
}

.player-track-sub {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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

.player-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.player-time {
  color: var(--text-dim);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
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
  .player-bar { padding: 0 12px; gap: 10px; }
  .player-track-name { font-size: 12px; }
  .ctrl-btn { width: 36px; height: 36px; }
}
</style>
