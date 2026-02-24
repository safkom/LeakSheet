<script setup>
import { computed } from 'vue'
import { playTrack, isStreamable, playerState } from '../composables/usePlayer.js'

const props = defineProps({
  version: Object,
  artistName: String,
  eraName: String,
})

const canStream = computed(() => isStreamable(props.version))

const isCurrentTrack = computed(() => {
  return playerState.track === props.version
})

function handlePlay() {
  playTrack(props.version, props.artistName, props.eraName)
}

function qualityClass(q) {
  if (!q) return 'q-na'
  const l = q.toLowerCase()
  if (l.includes('og') || l.includes('lossless')) return 'q-og'
  if (l.includes('cd')) return 'q-cd'
  if (l.includes('high')) return 'q-hq'
  if (l.includes('low')) return 'q-lq'
  if (l.includes('recording')) return 'q-rec'
  return 'q-na'
}

const badgeEmoji = computed(() => {
  const b = props.version.badge
  if (!b) return null
  const map = { best: '⭐', special: '✨', worst: '🗑️', grail: '🏆', wanted: '🏅' }
  return map[b] || null
})
</script>

<template>
  <button class="version-row" :class="{ playing: isCurrentTrack }" @click="handlePlay">
    <div class="v-play" :class="{ streamable: canStream }">
      <!-- Animated equalizer when playing -->
      <svg v-if="isCurrentTrack && playerState.isPlaying" viewBox="0 0 16 16" width="12" height="12" class="eq-icon">
        <rect class="eq-bar eq-1" x="1" y="6" width="3" height="10" rx="1" fill="currentColor"/>
        <rect class="eq-bar eq-2" x="6" y="3" width="3" height="13" rx="1" fill="currentColor"/>
        <rect class="eq-bar eq-3" x="11" y="5" width="3" height="11" rx="1" fill="currentColor"/>
      </svg>
      <svg v-else viewBox="0 0 16 16" width="12" height="12">
        <path fill="currentColor" d="M4 2l12 6-12 6z"/>
      </svg>
    </div>

    <div class="v-quality-col">
      <span v-if="version.quality" class="quality-badge" :class="qualityClass(version.quality)">
        {{ version.quality }}
      </span>
    </div>

    <div class="v-name">
      <span v-if="badgeEmoji" class="v-badge">{{ badgeEmoji }}</span>
      <span class="v-title">{{ version.name }}</span>
      <span v-if="version.version_tag" class="v-tag">[{{ version.version_tag }}]</span>
      <span v-if="version.collaboration" class="v-credit">(with {{ version.collaboration }})</span>
      <span v-if="version.featuring" class="v-credit">(feat. {{ version.featuring }})</span>
      <span v-if="version.producers" class="v-credit prod">(prod. {{ version.producers }})</span>
      <span v-if="version.refs" class="v-credit ref">(ref. {{ version.refs }})</span>
      <span v-if="version.alt_titles?.length" class="v-alt">
        <span v-for="(alt, i) in version.alt_titles" :key="i">({{ alt }})</span>
      </span>
    </div>

    <div class="v-meta">
      <span v-if="version.track_length" class="v-length">
        {{ version.track_length }}
      </span>
    </div>
  </button>
</template>

<style scoped>
.version-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 6px;
  border-radius: var(--radius-sm);
  transition: background 0.1s;
  font-size: 12px;
}

.version-row:hover {
  background: var(--bg-card);
}

.v-play {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  transition: color 0.1s;
  opacity: 0.35;
}

.v-play.streamable {
  opacity: 1;
}

.version-row:hover .v-play {
  color: var(--accent);
  opacity: 1;
}

.version-row.playing .v-play {
  color: var(--accent);
  opacity: 1;
}

.version-row.playing {
  background: rgba(88,166,255,0.05);
}

/* Equalizer animation */
.eq-icon { color: var(--accent); }
.eq-bar { transform-origin: bottom; animation: eq 0.8s ease-in-out infinite alternate; }
.eq-1 { animation-delay: 0s; }
.eq-2 { animation-delay: 0.2s; }
.eq-3 { animation-delay: 0.4s; }
@keyframes eq {
  0% { transform: scaleY(0.3); }
  100% { transform: scaleY(1); }
}

.v-name {
  flex: 1;
  font-weight: 400;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
  gap: 4px;
}

.v-badge {
  font-size: 12px;
  flex-shrink: 0;
}

.v-quality-col {
  flex-shrink: 0;
  min-width: 80px;
  display: flex;
  align-items: center;
}

.v-tag {
  color: var(--text-dim);
  font-size: 11px;
}

.v-credit {
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 400;
  opacity: 0.7;
  flex-shrink: 0;
}

.v-credit.prod {
  color: var(--text-dim);
}

.v-credit.ref {
  color: var(--text-dim);
  font-style: italic;
}

.v-alt {
  color: var(--text-dim);
  font-size: 10px;
  font-style: italic;
  opacity: 0.5;
  flex-shrink: 0;
}

.v-title {
  overflow: hidden;
  text-overflow: ellipsis;
}

.v-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.quality-badge {
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}

.q-og { background: rgba(78,205,196,0.15); color: var(--badge-og); }
.q-hq { background: rgba(88,166,255,0.15); color: var(--badge-hq); }
.q-cd { background: rgba(163,113,247,0.15); color: var(--badge-cd); }
.q-lq { background: rgba(240,136,62,0.15); color: var(--badge-lq); }
.q-rec { background: rgba(210,168,255,0.15); color: var(--badge-recording); }
.q-na { background: rgba(82,90,101,0.15); color: var(--badge-na); }

.v-length {
  color: var(--text-dim);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .version-row { font-size: 11px; gap: 6px; }
  .quality-badge { font-size: 8px; }
}
</style>
